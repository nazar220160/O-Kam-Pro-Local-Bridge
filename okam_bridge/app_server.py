"""Browser account app layered over the authenticated local media server."""

from http.cookies import SimpleCookie, CookieError
import json
import base64
import binascii
import threading
import hmac
from urllib.parse import urlsplit
from .web import BridgeServer, Handler
from .accounts import AccountError, WorkspaceError

COOKIE = "okam_account"


class AppServer(BridgeServer):
    def __init__(self, address, manager, token=""):
        self.manager = manager
        self._closing = threading.Event()
        self._reaper = None
        super().__init__(address, {}, token, handler_class=AppHandler)
        self._reaper = threading.Thread(target=self._prune, daemon=True)
        self._reaper.start()

    def _prune(self):
        while not self._closing.wait(60):
            self.manager.prune()

    def server_close(self):
        self._closing.set()
        if self._reaper:
            self._reaper.join(timeout=2)
        super().server_close()
        self.manager.close()


class AppHandler(Handler):
    def _key(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return cookie[COOKIE].value if COOKIE in cookie else None
        except CookieError:
            return None

    def _is_media(self):
        parts = urlsplit(self.path).path.strip("/").split("/")
        return (
            len(parts) == 4
            and parts[:2] == ["api", "cameras"]
            and parts[3] in ("snapshot.jpg", "mjpeg", "stream.h264")
        )

    def _player_workspace(self):
        if not self._is_media():
            return None
        try:
            scheme, encoded = self.headers.get("Authorization", "").split(" ", 1)
            if scheme.lower() != "basic":
                return None
            user, token = (
                base64.b64decode(encoded, validate=True).decode().split(":", 1)
            )
            if user != "player":
                return None
            return self.server.manager.player_workspace(token)
        except (ValueError, UnicodeError, binascii.Error):
            return None

    def _gateway_authorized(self):
        supplied = self.headers.get("X-Bridge-Gateway", "")
        return bool(
            self.server.token
            and supplied
            and hmac.compare_digest(supplied.encode(), self.server.token.encode())
        )

    def _authorized(self):
        bearer = self.headers.get("Authorization", "").startswith("Bearer ")
        return (
            self._gateway_authorized()
            or bool(bearer and self.server.manager.get(self._key()))
            or bool(self._player_workspace())
            or super()._authorized()
        )

    def _origin_allowed(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host")
        if self._gateway_authorized():
            host = self.headers.get("X-Forwarded-Host", host)
        try:
            parsed = urlsplit(origin)
            return parsed.scheme in ("http", "https") and parsed.netloc == host
        except ValueError:
            return False

    def _workspace(self):
        return self._player_workspace() or self.server.manager.get(self._key())

    def _cameras(self):
        workspace = self._workspace()
        return workspace.cameras if workspace else {}

    def _json(self, status, value, headers=None):
        return self._send(
            status,
            json.dumps(value, ensure_ascii=False),
            "application/json; charset=utf-8",
            headers,
        )

    def do_GET(self):
        if not self._host_allowed():
            return self._json(403, {"error": "forbidden_host"})
        path = urlsplit(self.path).path
        if path == "/health":
            return self._json(
                200,
                {
                    "ok": True,
                    "mode": "api",
                    "version": __import__("okam_bridge").__version__,
                },
            )
        if path == "/":
            return self._json(
                200,
                {
                    "service": "O-Kam Pro Local Bridge",
                    "version": __import__("okam_bridge").__version__,
                    "docs": "/docs/",
                    "openapi": "/openapi.json",
                },
            )
        if path == "/openapi.json":
            from .api_schema import openapi

            return self._json(200, openapi())
        if path in ("/docs", "/docs/"):
            from .api_schema import docs_html

            return self._send(200, docs_html())
        if path == "/controls.js":
            return self._json(404, {"error": "not_found"})
        if not self._authorized():
            return self._json(
                401,
                {"error": "bridge_auth_required"},
                (
                    {"WWW-Authenticate": 'Basic realm="O-Kam player"'}
                    if self._is_media()
                    else None
                ),
            )
        workspace = self._workspace()
        if workspace is None:
            return self._json(
                401,
                {"error": "account_login_required"},
                (
                    {"WWW-Authenticate": 'Basic realm="O-Kam player"'}
                    if self._is_media()
                    else None
                ),
            )
        if path == "/api/account/player":
            return self._json(
                200, {"username": "player", "password": workspace.player_token}
            )
        if path == "/api/account":
            return self._json(
                200,
                {
                    "username": workspace.username,
                    "camera_count": len(workspace.records),
                },
            )
        if path == "/api/cameras":
            return self._json(200, workspace.catalog())
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "cameras"]:
            camera = next((c for c in workspace.catalog() if c["id"] == parts[2]), None)
            return (
                self._json(200, camera)
                if camera
                else self._json(404, {"error": "camera_not_found"})
            )
        if len(parts) == 4 and parts[:2] == ["api", "cameras"]:
            if parts[3] == "services":
                try:
                    return self._json(200, workspace.services(parts[2]))
                except KeyError:
                    return self._json(404, {"error": "camera_not_found"})
                except WorkspaceError as error:
                    return self._json(400, {"error": str(error)})
            if parts[3] == "details":
                try:
                    return self._json(200, workspace.inspect(parts[2]))
                except KeyError:
                    return self._json(404, {"error": "camera_not_found"})
            return super().do_GET()
        return self._json(404, {"error": "not_found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/login":
            return self._json(404, {"error": "not_found"})
        if not self._host_allowed():
            return self._json(403, {"error": "forbidden_host"})
        if not self._origin_allowed():
            return self._json(403, {"error": "forbidden_origin"})
        if not self._authorized():
            return self._json(401, {"error": "bridge_auth_required"})
        if (
            self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            return self._json(415, {"error": "json_required"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                raise ValueError
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, UnicodeError):
            return self._json(400, {"error": "invalid_json"})
        try:
            if path == "/api/account/login":
                old = self._key()
                key = self.server.manager.login(
                    data.get("username"), data.get("password")
                )
                if old:
                    self.server.manager.logout(old)
                workspace = self.server.manager.get(key)
                return self._json(
                    200,
                    {
                        "username": workspace.username,
                        "camera_count": len(workspace.records),
                        "session_token": key,
                        "expires_in": int(self.server.manager.ttl),
                    },
                    {
                        "Set-Cookie": f"{COOKIE}={key}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200"
                    },
                )
            workspace = self._workspace()
            if workspace is None:
                return self._json(401, {"error": "account_login_required"})
            if path == "/api/account/logout":
                self.server.manager.logout(self._key())
                return self._json(
                    200,
                    {"ok": True},
                    {
                        "Set-Cookie": f"{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
                    },
                )
            if path == "/api/account/refresh":
                workspace.refresh()
                return self._json(200, workspace.catalog())
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "cameras"]:
                if parts[3] == "credentials":
                    return self._json(200, workspace.reveal_credentials(parts[2]))
                if parts[3] == "control":
                    return self._json(
                        200,
                        workspace.control(
                            parts[2], data.get("action"), data.get("args")
                        ),
                    )
                if parts[3] == "connect":
                    workspace.connect(
                        parts[2],
                        data.get("ip") or None,
                        data.get("substream", 1),
                        data.get("quality"),
                    )
                    return self._json(202, {"ok": True, "state": "preparing"})
                if parts[3] == "disconnect":
                    workspace.disconnect(parts[2])
                    return self._json(200, {"ok": True})
            return self._json(404, {"error": "not_found"})
        except AccountError:
            return self._json(401, {"error": "account_login_failed"})
        except KeyError:
            return self._json(404, {"error": "camera_not_found"})
        except WorkspaceError as error:
            code = str(error)
            return self._json(
                409 if code == "connection_in_progress" else 400, {"error": code}
            )
        except Exception:
            return self._json(502, {"error": "account_service_unavailable"})
