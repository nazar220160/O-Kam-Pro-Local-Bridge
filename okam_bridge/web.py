"""Local HTTP viewer, authenticated status, snapshots and native video."""

import base64
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import time
from urllib.parse import parse_qs, urlsplit


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, cameras, token="", handler_class=None):
        self.cameras = cameras
        self.token = token
        self.cookie_key = secrets.token_bytes(32)
        super().__init__(address, handler_class or Handler)

    def cookie(self):
        expires = str(int(time.time()) + 86400)
        sig = hmac.new(self.cookie_key, expires.encode(), hashlib.sha256).hexdigest()
        return expires + "." + sig

    def valid_cookie(self, value):
        try:
            expires, sig = value.split(".", 1)
            expected = hmac.new(
                self.cookie_key, expires.encode(), hashlib.sha256
            ).hexdigest()
            return int(expires) > time.time() and hmac.compare_digest(sig, expected)
        except (ValueError, AttributeError):
            return False


class Handler(BaseHTTPRequestHandler):
    server_version = "O-KAM-Local-Bridge/0.6.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_):
        # Requests can carry browser cookies and Basic headers; never log them.
        pass

    def _authorized(self):
        token = self.server.token
        if not token:
            return True
        auth = self.headers.get("Authorization", "")
        try:
            if auth.startswith("Basic "):
                decoded = base64.b64decode(auth[6:], validate=True).decode()
                return hmac.compare_digest(
                    decoded.encode(), ("bridge:" + token).encode()
                )
            if auth.startswith("Bearer "):
                return hmac.compare_digest(auth[7:].encode(), token.encode())
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            return bool(
                cookies.get("okam_session")
                and self.server.valid_cookie(cookies["okam_session"].value)
            )
        except (ValueError, UnicodeError):
            return False

    def _send(
        self, status, body, content_type="text/html; charset=utf-8", headers=None
    ):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _host_allowed(self):
        try:
            host = urlsplit("http://" + self.headers.get("Host", "")).hostname
        except ValueError:
            return False
        if self.server.server_address[0] in ("127.0.0.1", "localhost"):
            return host in ("127.0.0.1", "localhost")
        return bool(host)

    def _cameras(self):
        return self.server.cameras

    def do_POST(self):
        if not self._host_allowed():
            return self._send(403, "Forbidden host")
        if urlsplit(self.path).path != "/login":
            return self._send(404, "Not found")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._send(400, "Invalid request")
        if not 0 < size <= 2048:
            return self._send(400, "Invalid request")
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            return self._send(403, "Forbidden origin")
        body = self.rfile.read(size).decode(errors="replace")
        value = parse_qs(body).get("token", [""])[0]
        if not hmac.compare_digest(value.encode(), self.server.token.encode()):
            return self._send(401, "Incorrect access token")
        self._send(
            303,
            "",
            headers={
                "Location": "/",
                "Set-Cookie": "okam_session="
                + self.server.cookie()
                + "; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400",
            },
        )

    def do_GET(self):
        if not self._host_allowed():
            return self._send(403, "Forbidden host")
        path = urlsplit(self.path).path
        if path == "/health":
            return self._send(200, '{"ok":true}', "application/json")
        if not self._authorized():
            return self._send(
                401,
                "Authentication required",
                headers={"WWW-Authenticate": 'Basic realm="O-KAM Bridge"'},
            )
        if path == "/":
            return self._send(
                200,
                json.dumps(
                    {"service": "O-Kam Pro Local Bridge", "mode": "static-config"}
                ),
                "application/json",
            )
        if path == "/api/cameras":
            data = [
                {"id": k, "name": c.name, **c.status()}
                for k, c in self._cameras().items()
            ]
            return self._send(
                200,
                json.dumps(data, ensure_ascii=False),
                "application/json; charset=utf-8",
            )
        parts = path.strip("/").split("/")
        if len(parts) != 4 or parts[:2] != ["api", "cameras"]:
            return self._send(404, "Not found")
        camera = self._cameras().get(parts[2])
        if camera is None:
            return self._send(404, "Camera not found")
        endpoint = parts[3]
        if endpoint not in ("snapshot.jpg", "mjpeg", "stream.h264"):
            return self._send(404, "Not found")
        try:
            lens = int(parse_qs(urlsplit(self.path).query).get("lens", ["0"])[0])
            if not 0 <= lens <= 15:
                raise ValueError
        except ValueError:
            return self._send(400, "Invalid lens index")
        kind = "h264" if endpoint == "stream.h264" else "jpeg"
        frames = camera.frames(kind, lens=lens) if lens else camera.frames(kind)
        try:
            # Do not report success until a real media frame is available.
            first = next(frames, None)
            if first is None:
                return self._send(503, "Camera unavailable")
            if endpoint == "snapshot.jpg":
                return self._send(200, first, "image/jpeg")
            self.send_response(200)
            self.send_header(
                "Content-Type",
                (
                    "video/h264"
                    if endpoint == "stream.h264"
                    else "multipart/x-mixed-replace; boundary=frame"
                ),
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()

            def write(frame):
                if endpoint == "mjpeg":
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(frame)).encode()
                        + b"\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )
                else:
                    self.wfile.write(frame)
                self.wfile.flush()

            write(first)
            for frame in frames:
                write(frame)
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        finally:
            frames.close()
