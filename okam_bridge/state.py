"""Encrypted, atomic runtime state and bounded background camera restoration."""

import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .accounts import AccountWorkspace, Record
from .vendor.account import AccountDevice

MAX_STATE = 8 * 1024 * 1024


class StateStore:
    def __init__(self, root):
        self.root = Path(root).expanduser().absolute()
        if self.root.is_symlink():
            raise ValueError("Unsafe state directory")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.path = self.root / "sessions.enc"
        keypath = self.root / "state.key"
        if keypath.is_symlink() or self.path.is_symlink():
            raise ValueError("Unsafe state file")
        if not keypath.exists():
            if self.path.exists():
                raise ValueError("State encryption key is missing")
            fd = os.open(keypath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(secrets.token_bytes(32))
                stream.flush()
                os.fsync(stream.fileno())
        keypath.chmod(0o600)
        key = keypath.read_bytes()
        if len(key) != 32:
            raise ValueError("Invalid state encryption key")
        if self.path.exists():
            self.path.chmod(0o600)
        self.cipher = AESGCM(key)
        self.lock = threading.RLock()
        self.digest = None

    def load(self):
        with self.lock:
            if not self.path.exists():
                return {"version": 1, "sessions": []}
            if self.path.is_symlink() or self.path.stat().st_size > MAX_STATE:
                raise ValueError("Invalid persistent state")
            try:
                wire = self.path.read_bytes()
                data = json.loads(
                    self.cipher.decrypt(wire[:12], wire[12:], b"okam-state-v1")
                )
                if (
                    data.get("version") != 1
                    or not isinstance(data.get("sessions"), list)
                    or len(data["sessions"]) > 16
                ):
                    raise ValueError()
                return data
            except Exception:
                raise ValueError(
                    "Persistent state could not be decrypted; preserve state.key and sessions.enc together"
                ) from None

    def save(self, data):
        plain = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        if len(plain) > MAX_STATE - 64:
            raise ValueError("Persistent state limit reached")
        digest = hashlib.sha256(plain).digest()
        with self.lock:
            if self.digest == digest:
                return
            nonce = secrets.token_bytes(12)
            wire = nonce + self.cipher.encrypt(nonce, plain, b"okam-state-v1")
            temporary = self.root / (".state-" + secrets.token_hex(8))
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(wire)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                directory = os.open(self.root, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                self.digest = digest
            finally:
                temporary.unlink(missing_ok=True)


class StateService:
    def __init__(self, manager, exports, root):
        self.manager = manager
        self.exports = exports
        self.store = StateStore(root)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.restoring = set()
        self.workers = []
        self.retry = {}
        self.account_retry = {}
        self.account_workers = {}
        self.error = None
        self.frozen = False
        manager.persistence = self

    def snapshot(self):
        sessions = []
        with self.manager.lock:
            workspaces = list(self.manager.workspaces.items())
        for token, workspace in workspaces:
            with workspace.lock:
                if workspace.closed:
                    continue
                records = []
                for record in workspace.records.values():
                    records.append(
                        {
                            "id": record.id,
                            "device": {
                                "uid": record.device.uid,
                                "name": record.device.name,
                                "device_password": record.device.device_password,
                                "security": record.device.security,
                            },
                            "metadata": record.account_metadata,
                            "check": record.check_value,
                            "account_token": record.account_token,
                            "ip": record.ip,
                            "substream": record.substream,
                            "quality": record.quality,
                            "wanted": record.wanted,
                            "config": record.cached_config,
                        }
                    )
                sessions.append(
                    json.loads(
                        json.dumps(
                            {
                                "token": token,
                                "username": workspace.username,
                                "account_id": workspace.account_id,
                                "player_token": workspace.player_token,
                                "expires_at": workspace.expires_at,
                                "login_token": getattr(
                                    workspace.client, "login_token", None
                                ),
                                "device_digest": getattr(
                                    workspace.client, "_device_digest", None
                                ),
                                "records": records,
                                "exports": dict(workspace.saved_exports),
                                "recordings": dict(workspace.saved_recordings),
                            }
                        )
                    )
                )
        return {"version": 1, "sessions": sessions}

    def checkpoint(self):
        with self.lock:
            if not self.frozen:
                self.store.save(self.snapshot())

    def start(self):
        data = self.store.load()
        for session in data["sessions"]:
            expires = session.get("expires_at", time.time() + self.manager.ttl)
            if expires < time.time() and not any(
                v.get("enabled") for v in session.get("exports", {}).values()
            ):
                continue
            client = self.manager.client_factory()
            client.user_id = session["account_id"]
            client.login_token = session.get("login_token")
            client._device_digest = session.get("device_digest")
            client.raw_items = []
            devices = [AccountDevice(**row["device"]) for row in session["records"]]
            workspace = AccountWorkspace(
                session["username"], client, devices, self.manager.backend
            )
            workspace.exports = self.exports
            workspace.player_token = session["player_token"]
            workspace.expires_at = expires
            workspace.saved_exports = session.get("exports", {})
            workspace.saved_recordings = session.get("recordings", {})
            for row in session["records"]:
                record = workspace.records[row["id"]]
                record.account_metadata = row["metadata"]
                record.check_value = row["check"]
                record.account_token = row.get("account_token")
                record.ip, record.substream, record.quality = (
                    row["ip"],
                    row["substream"],
                    row["quality"],
                )
                record.wanted = bool(row["wanted"])
                record.cached_config = row.get("config")
                # Recreate enough account metadata for later catalog refresh.
                client.raw_items.append(
                    {**row["device"], "doubleCheck": record.check_value}
                )
            self.manager.workspaces[session["token"]] = workspace
        self.thread = threading.Thread(
            target=self._run, daemon=True, name="bridge-state"
        )
        self.thread.start()

    def _restore_camera(self, workspace, record, marker):
        try:
            with workspace.lock:
                if workspace.closed or not record.wanted or self.stop.is_set():
                    return
                record.generation += 1
                generation = record.generation
                record.phase = "preparing"
                record.error = None
                config = dict(record.cached_config) if record.cached_config else None
            workspace._connect(
                record,
                generation,
                record.ip,
                record.substream,
                record.quality,
                prepared=config,
            )
        finally:
            with self.lock:
                self.restoring.discard(marker)
                self.retry[marker] = time.monotonic() + 10

    def _refresh_account(self, workspace):
        success = False
        try:
            with workspace.auth_lock:
                if workspace.closed or self.stop.is_set():
                    return
                devices = workspace.client.refresh_login()
                if not workspace.closed:
                    workspace.adopt_client(workspace.client, devices)
                    success = True
        except Exception:
            pass  # Cached native credentials can still work when cloud is down.
        finally:
            with self.lock:
                self.account_retry[id(workspace)] = time.monotonic() + (
                    3600 if success else 30
                )

    def _reconcile(self):
        with self.manager.lock:
            workspaces = list(self.manager.workspaces.values())
        for workspace in workspaces:
            with self.lock:
                worker = self.account_workers.get(id(workspace))
                if (
                    hasattr(workspace.client, "refresh_login")
                    and getattr(workspace.client, "_device_digest", None)
                    and not (worker and worker.is_alive())
                    and time.monotonic() >= self.account_retry.get(id(workspace), 0)
                ):
                    worker = threading.Thread(
                        target=self._refresh_account, args=(workspace,), daemon=True
                    )
                    self.account_workers[id(workspace)] = worker
                    worker.start()
            with workspace.lock:
                if workspace.closed:
                    continue
                records = list(workspace.records.values())
            for record in records:
                marker = (id(workspace), record.id)
                with workspace.lock:
                    wanted, phase = record.wanted, record.phase
                    connected = record.id in workspace.cameras
                    saved = dict(workspace.saved_exports.get(record.id, {}))
                    recording = dict(workspace.saved_recordings.get(record.id, {}))
                if (
                    wanted
                    and not connected
                    and phase
                    not in ("preparing", "resolving", "discovering", "starting")
                ):
                    with self.lock:
                        if (
                            marker not in self.restoring
                            and time.monotonic() >= self.retry.get(marker, 0)
                            and len(self.restoring) < 4
                        ):
                            self.restoring.add(marker)
                            worker = threading.Thread(
                                target=self._restore_camera,
                                args=(workspace, record, marker),
                                daemon=True,
                            )
                            self.workers = [w for w in self.workers if w.is_alive()]
                            self.workers.append(worker)
                            worker.start()
                # Serialize automatic starts with explicit off/disconnect. Never
                # replay a stale intent read before the user's stop action.
                with workspace.lock:
                    if workspace.closed or record.id not in workspace.cameras:
                        continue
                    saved = dict(workspace.saved_exports.get(record.id, {}))
                    recording = dict(workspace.saved_recordings.get(record.id, {}))
                    if saved.get("enabled") and not self.exports._find(
                        workspace, record.id
                    ):
                        try:
                            self.exports.configure(workspace, record.id, saved)
                        except (ValueError, OSError):
                            continue  # MediaMTX may start after the API health check.
                    if recording.get("enabled") and self.exports._find(
                        workspace, record.id
                    ):
                        status = self.exports.archive.status(workspace, record.id)
                        if not status["recording_enabled"]:
                            try:
                                self.exports.archive.set_recording(
                                    workspace, record.id, recording
                                )
                            except (ValueError, OSError):
                                pass

    def _run(self):
        while not self.stop.is_set():
            try:
                self._reconcile()
                self.checkpoint()
                self.error = None
            except Exception:
                self.error = "state_checkpoint_or_restore_failed"
            self.stop.wait(1)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        with self.lock:
            try:
                self.store.save(self.snapshot())
            finally:
                self.frozen = True
