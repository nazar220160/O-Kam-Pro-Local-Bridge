"""Account-isolated, in-memory camera catalogs and connection workspaces."""

from dataclasses import dataclass, field
import hashlib
import ipaddress
import secrets
import re
import threading
import time
from .vendor.account import Eye4AccountClient, AccountDevice, AccountError
from .vendor.p2p import resolve_client_id, get_service_parameter, valid_vp_security
from .transport import discover_lan, CS2Error
from .camera import Camera
from .credentials import CredentialDecoder, CredentialError
from .controls import ControlError, public_fields


def public_account_metadata(item):
    result = {}
    aliases = {
        "model": ("model", "device_model", "devicemodel"),
        "firmware": ("firmware", "version", "sys_ver"),
        "device_type": ("device_type", "devicetype"),
        "shared": ("isShare", "is_share", "shared"),
    }
    for public, names in aliases.items():
        for name in names:
            value = item.get(name)
            if isinstance(value, str) and value.strip().lower() in (
                "",
                "null",
                "none",
                "undefined",
            ):
                continue
            if isinstance(value, (str, int, bool)) and not isinstance(value, float):
                result[public] = value[:200] if isinstance(value, str) else value
                break
    for name in ("online", "isOnline", "is_online"):
        if item.get(name) in (0, 1, True, False, "0", "1"):
            result["account_online"] = item[name] in (1, True, "1")
            break
    lowered = {str(k).lower(): v for k, v in item.items()}
    for name in ("lan_ip", "local_ip", "lanip", "localip", "innerip", "ip"):
        try:
            result["lan_ip"] = private_ipv4(lowered.get(name))
            break
        except WorkspaceError:
            pass
    return result


class CatalogClient(Eye4AccountClient):
    def __init__(self):
        super().__init__()
        self.raw_items = []
        self._device_digest = None
        self._state_lock = threading.Lock()
        self._closed = False

    def _request_json(self, method, path, **kwargs):
        with self._state_lock:
            if self._closed:
                raise AccountError("Session closed")
        result = super()._request_json(method, path, **kwargs)
        with self._state_lock:
            if self._closed:
                raise AccountError("Session closed")
            if path == "/PC/device/show":
                self.raw_items = result if isinstance(result, list) else []
                self._device_digest = kwargs.get("query", {}).get("pwd")
        return result

    def refresh_login(self):
        """Renew the vendor login using its persisted protocol digest."""
        if not self.user_id or not self._device_digest:
            raise AccountError("Account refresh is unavailable")
        result = self._request_json(
            "GET",
            "/login/token",
            query={
                "userid": self.user_id,
                "password": self._device_digest,
                "type": "PC",
            },
        )
        if not isinstance(result, dict) or not isinstance(result.get("token"), str):
            raise AccountError("Account session could not be renewed")
        self.login_token = result["token"]
        return self.refresh_devices()

    def refresh_devices(self):
        if not self.user_id or not self._device_digest:
            raise AccountError("Account refresh is unavailable")
        data = self._request_json(
            "GET",
            "/PC/device/show",
            query={"userid": self.user_id, "pwd": self._device_digest},
        )
        if not isinstance(data, list):
            raise AccountError("Camera catalog unavailable")
        devices = []
        for item in data:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("uid"), str)
                or not 4 <= len(item["uid"]) <= 256
            ):
                continue
            name = item.get("nickname")
            password = item.get("password")
            security = item.get("security")
            devices.append(
                AccountDevice(
                    uid=item["uid"],
                    name=name if isinstance(name, str) and name else "O-Kam camera",
                    device_password=password if isinstance(password, str) else "",
                    security=security if valid_vp_security(security) else None,
                )
            )
        return devices

    def clear(self):
        with self._state_lock:
            self._closed = True
            self.raw_items = []
            self._device_digest = None
            self.login_token = None
            self.user_id = None


class WorkspaceError(ValueError):
    pass


def private_ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
        if not address.is_private or address.is_multicast or address.is_unspecified:
            raise ValueError
    except (ValueError, TypeError):
        raise WorkspaceError("invalid_lan_ip") from None
    return str(address)


def native_credentials(record, account_id, decoder):
    """Cloud plaintext/external access and dual-auth native secrets may coexist."""
    password = record.device.device_password
    security = record.device.security
    encrypted = bool(security) and (
        not password or bool(re.fullmatch(r"[0-9a-fA-F]{32}", security))
    )
    if encrypted:
        if decoder is None:
            raise WorkspaceError("password_decoder_required")
        try:
            password = decoder.decode(security, record.check_value or account_id)
        except CredentialError as e:
            raise WorkspaceError(str(e)) from None
    if not password:
        raise WorkspaceError("native_credentials_unavailable")
    return password, encrypted


class LANBackend:
    def __init__(self, ffmpeg, credential_client=None):
        self.ffmpeg = ffmpeg
        self.decoder = CredentialDecoder(credential_client)

    def prepare(self, record, account_id, ip, substream):
        uid = resolve_client_id(record.device.uid)
        if len(uid) != 15:
            raise WorkspaceError("unsupported_protocol")
        parameter = get_service_parameter(uid)
        password, encrypted = native_credentials(record, account_id, self.decoder)
        config = {
            "id": record.id,
            "name": record.device.name,
            "transport_uid": uid,
            "service_parameter": parameter,
            "account_id": account_id,
            "username": "admin",
            "password": password,
            "compatibility_password": "888888",
            "ports": [32108, 32100],
            "substream": substream,
        }
        if encrypted:
            config["account_token"] = record.account_token
        known_ip = ip or record.account_metadata.get("lan_ip")
        if known_ip:
            config["ip"] = private_ipv4(known_ip)
        else:
            config["ip"] = discover_lan(uid, parameter, timeout=6)["ip"]
        return config

    def camera(self, config):
        return Camera(config, self.ffmpeg)


@dataclass
class Record:
    id: str
    device: AccountDevice = field(repr=False)
    account_metadata: dict = field(default_factory=dict)
    check_value: str | None = field(default=None, repr=False)
    account_token: str | None = field(default=None, repr=False)
    phase: str = "disconnected"
    error: str | None = None
    generation: int = 0
    instance: object = None
    ip: str | None = None
    substream: int = 1
    quality: str | None = None
    wanted: bool = False
    cached_config: dict | None = field(default=None, repr=False)


class AccountWorkspace:
    def __init__(self, username, client, devices, backend):
        self.username = username
        self.client = client
        self.account_id = client.user_id
        self.backend = backend
        self.lock = threading.RLock()
        self.auth_lock = threading.RLock()
        self.closed = False
        self.records = {}
        self.cameras = {}
        self.created = time.monotonic()
        self.expires_at = time.time() + 365 * 24 * 3600
        self.player_token = secrets.token_urlsafe(32)
        self.exports = None
        self.saved_exports = {}
        self.saved_recordings = {}
        self._sync(devices)

    def _sync(self, devices):
        raw = {
            item.get("uid"): item
            for item in self.client.raw_items
            if isinstance(item, dict)
        }
        stale = []
        removed = []
        with self.lock:
            if self.closed:
                return
            fresh = {}
            for d in devices:
                key = hashlib.sha256(d.uid.encode()).hexdigest()[:16]
                r = self.records.get(key) or Record(key, d)
                r.device = d
                r.account_metadata = public_account_metadata(raw.get(d.uid, {}))
                r.check_value = str(
                    raw.get(d.uid, {}).get("doubleCheck") or self.account_id
                )
                r.account_token = getattr(self.client, "login_token", None)
                fresh[key] = r
            for key, r in self.records.items():
                if key not in fresh:
                    removed.append(key)
                    r.generation += 1
                    if r.instance:
                        stale.append(r.instance)
                    self.cameras.pop(key, None)
            self.records = fresh
        if self.exports:
            for key in removed:
                self.exports.disable(self, key)
        for camera in stale:
            camera.stop()

    def adopt_client(self, client, devices):
        with self.auth_lock:
            old_client = self.client
            self.client = client
            self._sync(devices)
            with self.lock:
                for record in self.records.values():
                    if record.cached_config and record.account_token:
                        record.cached_config["account_token"] = record.account_token
                    if record.instance and record.account_token:
                        with record.instance.lock:
                            record.instance.config["account_token"] = (
                                record.account_token
                            )
            if old_client is not client and hasattr(old_client, "clear"):
                old_client.clear()

    def refresh(self):
        with self.lock:
            if self.closed:
                raise WorkspaceError("session_expired")
        self._sync(self.client.refresh_devices())

    def catalog(self):
        with self.lock:
            result = []
            for r in self.records.values():
                live = r.instance.status() if r.instance else {}
                state = live.get("state", "idle") if r.phase == "ready" else r.phase
                result.append(
                    {
                        "id": r.id,
                        "name": r.device.name,
                        "device_id": r.device.uid,
                        "account_metadata": dict(r.account_metadata),
                        "state": state,
                        "error": r.error or live.get("last_error"),
                        "ip": r.ip,
                        "substream": r.substream,
                        "quality": r.quality,
                        "viewable": r.id in self.cameras,
                        "capability": (
                            "native"
                            if r.device.device_password
                            else (
                                "encrypted"
                                if r.device.security
                                else "native_credentials_required"
                            )
                        ),
                        "protocol": "CS2/PPPP" if r.instance else None,
                        "lenses": live.get("lenses", []),
                        "metadata": live.get("metadata", {}),
                        "lens_metadata": live.get("lens_metadata", []),
                        "viewers": live.get("viewers", 0),
                        "last_frame": live.get("last_frame"),
                    }
                )
            return result

    def connect(self, camera_id, ip=None, substream=1, quality=None):
        if quality is not None and (
            not isinstance(quality, str) or quality not in ("high", "medium", "low")
        ):
            raise WorkspaceError("invalid_quality")
        if ip:
            ip = private_ipv4(ip)
        if type(substream) is not int or substream not in (0, 1, 2):
            raise WorkspaceError("invalid_stream")
        with self.lock:
            if self.closed:
                raise WorkspaceError("session_expired")
            if camera_id not in self.records:
                raise KeyError(camera_id)
            r = self.records[camera_id]
            if r.phase in ("preparing", "resolving", "discovering", "starting"):
                raise WorkspaceError("connection_in_progress")
            old = r.instance
            r.instance = None
            self.cameras.pop(camera_id, None)
            r.generation += 1
            generation = r.generation
            r.wanted = True
            r.phase = "preparing"
            r.error = None
            r.substream = substream
            r.ip = ip
            r.quality = quality
        if old:
            old.stop()
        threading.Thread(
            target=self._connect,
            args=(r, generation, ip, substream, quality),
            daemon=True,
        ).start()

    def _connect(self, r, generation, ip, substream, quality=None, prepared=None):
        camera = None
        success = False
        try:
            with self.lock:
                if self.closed or r.generation != generation:
                    return
            config = (
                dict(prepared)
                if prepared
                else self.backend.prepare(r, self.account_id, ip, substream)
            )
            if quality is not None:
                config["quality"] = quality
            with self.lock:
                if self.closed or r.generation != generation:
                    return
                r.phase = "starting"
                r.ip = config["ip"]
                r.cached_config = dict(config)
                camera = self.backend.camera(config)
                r.instance = camera
            frames = camera.frames("jpeg")
            try:
                first = next(frames, None)
            finally:
                frames.close()
            if not first:
                raise WorkspaceError(
                    camera.status().get("last_error") or "video_unavailable"
                )
            with self.lock:
                if self.closed or r.generation != generation:
                    return
                self.cameras[r.id] = camera
                r.phase = "ready"
                success = True
        except WorkspaceError as error:
            self._failure(r, generation, str(error))
        except CS2Error:
            self._failure(r, generation, "camera_unavailable")
        except Exception:
            self._failure(r, generation, "connection_failed")
        finally:
            if camera and not success:
                camera.stop()
            if not success:
                with self.lock:
                    if r.generation == generation:
                        r.instance = None

    def _failure(self, r, generation, error):
        # Codes here are internal constants, not raw URLs/vendor responses.
        allowed = {
            "unsupported_protocol",
            "native_credentials_unavailable",
            "video_unavailable",
            "no_lan_reply",
            "camera_password_rejected",
            "camera_unavailable",
            "connection_failed",
            "camera_unavailable_or_video_interrupted",
            "password_decoder_required",
            "encrypted_credentials_invalid",
            "credential_client_invalid",
            "credential_key_ambiguous",
            "credential_key_not_found",
            "crypto_dependency_required",
        }
        if error.startswith("video_start_rejected:"):
            error = "video_start_rejected"
        if error not in allowed and error != "video_start_rejected":
            error = "connection_failed"
        with self.lock:
            if not self.closed and r.generation == generation:
                r.phase = "error"
                r.error = error

    def inspect(self, camera_id):
        with self.lock:
            r = self.records.get(camera_id)
            if r is None:
                raise KeyError(camera_id)
            camera = self.cameras.get(camera_id)
            raw = next(
                (
                    item
                    for item in self.client.raw_items
                    if isinstance(item, dict) and item.get("uid") == r.device.uid
                ),
                {},
            )
            result = (
                camera.inspect()
                if camera
                else {"groups": {}, "queries": {}, "capabilities": {}}
            )
            result["account"] = public_fields(
                raw, (r.device.device_password, r.device.security)
            )
            return result

    def services(self, camera_id):
        from .services import inspect_services

        with self.lock:
            if self.closed:
                raise WorkspaceError("session_expired")
            record = self.records.get(camera_id)
            if record is None:
                raise KeyError(camera_id)
            ip = record.ip or record.account_metadata.get("lan_ip")
        if not ip:
            raise WorkspaceError("camera_ip_required")
        return inspect_services(camera_id, private_ipv4(ip), self.inspect(camera_id))

    def reveal_credentials(self, camera_id):
        with self.lock:
            if self.closed:
                raise WorkspaceError("session_expired")
            r = self.records.get(camera_id)
            if r is None:
                raise KeyError(camera_id)
            password, _ = native_credentials(
                r, self.account_id, getattr(self.backend, "decoder", None)
            )
            return {"username": "admin", "password": password}

    def control(self, camera_id, action, args=None):
        with self.lock:
            if self.closed:
                raise WorkspaceError("session_expired")
            if camera_id not in self.records:
                raise KeyError(camera_id)
            camera = self.cameras.get(camera_id)
        if camera is None:
            raise WorkspaceError("camera_not_streaming")
        try:
            return camera.control(action, args)
        except ControlError as e:
            raise WorkspaceError(str(e)) from None

    def disconnect(self, camera_id):
        if self.exports:
            self.exports.disable(self, camera_id)
        with self.lock:
            if camera_id not in self.records:
                raise KeyError(camera_id)
            r = self.records[camera_id]
            r.generation += 1
            camera = r.instance
            r.instance = None
            r.wanted = False
            r.phase = "disconnected"
            r.error = None
            self.cameras.pop(camera_id, None)
        if camera:
            camera.stop()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            cameras = []
            for r in self.records.values():
                r.generation += 1
                if r.instance:
                    cameras.append(r.instance)
                r.instance = None
            self.cameras.clear()
            self.records.clear()
            self.player_token = None
        if self.exports:
            self.exports.disable(self)
        for camera in cameras:
            camera.stop()
        if hasattr(self.client, "clear"):
            self.client.clear()
        self.account_id = None


class AccountManager:
    def __init__(self, client_factory=CatalogClient, backend=None, ttl=365 * 24 * 3600):
        self.client_factory = client_factory
        self.backend = backend
        self.ttl = ttl
        self.exports = None
        self.lock = threading.RLock()
        self.workspaces = {}
        self.closed = False

    def login(self, username, password):
        if (
            not isinstance(username, str)
            or not isinstance(password, str)
            or not username
            or not password
            or len(username) > 320
            or len(password) > 1024
        ):
            raise AccountError("Invalid account credentials")
        with self.lock:
            if self.closed:
                raise WorkspaceError("session_expired")
        self.prune()
        client = self.client_factory()
        try:
            devices = client.enumerate(username, password)
        finally:
            password = ""
        with self.lock:
            if self.closed:
                if hasattr(client, "clear"):
                    client.clear()
                raise WorkspaceError("session_expired")
            # A verified login resumes the same account's workspace, preserving
            # existing NVR connections rather than creating a parallel camera.
            for key, existing in self.workspaces.items():
                if (
                    not existing.closed
                    and existing.account_id == client.user_id
                    and existing.username.casefold() == username.casefold()
                ):
                    existing.adopt_client(client, devices)
                    existing.created = time.monotonic()
                    existing.expires_at = time.time() + self.ttl
                    return key
            if len(self.workspaces) >= 16:
                if hasattr(client, "clear"):
                    client.clear()
                raise WorkspaceError("too_many_sessions")
            workspace = AccountWorkspace(username, client, devices, self.backend)
            workspace.exports = self.exports
            workspace.expires_at = time.time() + self.ttl
            key = secrets.token_urlsafe(32)
            self.workspaces[key] = workspace
        return key

    def _retained(self, workspace):
        return any(v.get("enabled") for v in workspace.saved_exports.values()) or bool(
            workspace.exports and workspace.exports.has_workspace(workspace)
        )

    def get(self, key):
        with self.lock:
            workspace = self.workspaces.get(key)
        if (
            workspace
            and (
                time.monotonic() - workspace.created > self.ttl
                or time.time() > workspace.expires_at
            )
            and not self._retained(workspace)
        ):
            self.logout(key)
            return None
        return workspace

    def player_workspace(self, token):
        if not token:
            return None
        self.prune()
        with self.lock:
            return next(
                (
                    w
                    for w in self.workspaces.values()
                    if w.player_token and secrets.compare_digest(w.player_token, token)
                ),
                None,
            )

    def prune(self):
        with self.lock:
            keys = [
                key
                for key, w in self.workspaces.items()
                if (
                    time.monotonic() - w.created > self.ttl
                    or time.time() > w.expires_at
                )
                and not self._retained(w)
            ]
        for key in keys:
            self.logout(key)

    def logout(self, key):
        with self.lock:
            workspace = self.workspaces.pop(key, None)
        if workspace:
            persistence = getattr(self, "persistence", None)
            try:
                if persistence:
                    persistence.checkpoint()
            finally:
                workspace.close()

    def close(self):
        with self.lock:
            self.closed = True
            keys = list(self.workspaces)
        for key in keys:
            self.logout(key)
