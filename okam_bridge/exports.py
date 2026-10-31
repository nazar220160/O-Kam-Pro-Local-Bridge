"""Explicit, account-scoped bridge publications; native camera settings are untouched."""

from dataclasses import dataclass, field
import hmac
import os
import re
import secrets
import select
import socket
import subprocess
import threading
import time
import weakref
from urllib.parse import urlsplit, quote
from .export_motion import MotionController
from .onvif_events import EventBroker


class ExportError(ValueError):
    pass


def publisher_command(ffmpeg, url, fps=10, audio_fd=None):
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-fflags",
        "+genpts",
        "-thread_queue_size",
        "512",
        "-probesize",
        "100000",
        "-analyzeduration",
        "500000",
        "-f",
        "h264",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
    ]
    if audio_fd is not None:
        command += [
            "-thread_queue_size",
            "512",
            "-f",
            "alaw",
            "-ar",
            "8000",
            "-ac",
            "1",
            "-i",
            f"pipe:{audio_fd}",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:a",
            "aac",
            "-ar",
            "16000",
            "-b:a",
            "32k",
            "-af",
            "aresample=async=1:first_pts=0",
        ]
    else:
        command += ["-an"]
    command += [
        "-c:v",
        "copy",
        "-bsf:v",
        f"setts=ts=N/({fps}*TB)",
        "-flush_packets",
        "1",
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        "-muxdelay",
        "0.1",
        url,
    ]
    return command


class Publisher:
    def __init__(self, camera, lens, ffmpeg, url):
        self.camera = camera
        self.lens = lens
        self.ffmpeg = ffmpeg
        self.url = url
        self.stop_event = threading.Event()
        self.thread = None
        self.process = None
        self.lock = threading.Lock()
        self.written = 0
        self.error = None
        self.audio = False

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _write(self, process, data, fd=None, cancel=None):
        fd = process.stdin.fileno() if fd is None else fd
        remaining = memoryview(data)
        end = time.monotonic() + 5
        while (
            remaining
            and not self.stop_event.is_set()
            and not (cancel and cancel.is_set())
        ):
            if process.poll() is not None or time.monotonic() > end:
                raise BrokenPipeError
            if not select.select([], [fd], [], 0.25)[1]:
                continue
            try:
                n = os.write(fd, remaining)
            except BlockingIOError:
                continue
            remaining = remaining[n:]
        if self.stop_event.is_set():
            raise BrokenPipeError

    def _feed_audio(self, process, fd, cancel):
        frames = None
        try:
            os.set_blocking(fd, False)
            frames = self.camera.frames("audio", cancel=cancel)
            for data in frames:
                self._write(process, data, fd=fd, cancel=cancel)
                if cancel.is_set() or self.stop_event.is_set():
                    break
        except (OSError, ValueError, RuntimeError):
            pass
        finally:
            if frames:
                frames.close()
            os.close(fd)

    def _run(self):
        while not self.stop_event.is_set():
            process = None
            frames = None
            audio_thread = None
            audio_read = audio_write = None
            cycle_cancel = threading.Event()
            try:
                metadata = next(
                    (
                        x
                        for x in self.camera.status().get("lens_metadata", [])
                        if x.get("id") == self.lens
                    ),
                    {},
                )
                fps = metadata.get("reported_fps") or metadata.get("measured_fps") or 10
                fps = max(1, min(60, int(fps)))
                env = dict(os.environ)
                env.pop("FFREPORT", None)
                self.audio = bool(
                    self.camera.status().get("audio", {}).get("available")
                )
                if self.audio:
                    audio_read, audio_write = os.pipe()
                process = subprocess.Popen(
                    publisher_command(self.ffmpeg, self.url, fps, audio_read),
                    pass_fds=(audio_read,) if audio_read is not None else (),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    bufsize=0,
                    env=env,
                )
                with self.lock:
                    self.process = process
                    if self.stop_event.is_set():
                        process.terminate()
                if audio_read is not None:
                    os.close(audio_read)
                    audio_read = None
                    audio_thread = threading.Thread(
                        target=self._feed_audio,
                        args=(process, audio_write, cycle_cancel),
                        daemon=True,
                    )
                    audio_thread.start()
                    audio_write = None  # The feeder now owns and closes it.
                os.set_blocking(process.stdin.fileno(), False)
                frames = self.camera.frames(
                    "h264", lens=self.lens, cancel=self.stop_event
                )
                for frame in frames:
                    if self.stop_event.is_set():
                        break
                    if self.audio != bool(
                        self.camera.status().get("audio", {}).get("available")
                    ):
                        raise RuntimeError("audio_layout_changed")
                    self._write(process, frame)
                    self.written += 1
                    self.error = None
            except (OSError, ValueError, RuntimeError):
                self.error = "rtsp_publisher_unavailable"
            finally:
                cycle_cancel.set()
                if frames:
                    frames.close()
                if process:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                    if process.stdin:
                        process.stdin.close()
                if audio_thread:
                    audio_thread.join(timeout=6)
                for fd in (audio_read, audio_write):
                    if fd is not None:
                        os.close(fd)
                with self.lock:
                    self.process = None
            if not self.stop_event.is_set():
                self.stop_event.wait(2)

    def stop(self):
        self.stop_event.set()
        with self.lock:
            if self.process and self.process.poll() is None:
                try:
                    self.process.terminate()
                except OSError:
                    pass

    def join(self):
        if self.thread:
            self.thread.join(timeout=6)


@dataclass(repr=False)
class Publication:
    workspace: object
    camera_id: str
    export_id: str
    host: str
    onvif: bool
    password: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    stop: threading.Event = field(default_factory=threading.Event)
    publishers: dict = field(default_factory=dict)
    thread: object = None
    lock: object = field(default_factory=threading.RLock)
    motion: object = None
    event_thread: object = None
    alarm_state: object = None


class ExportManager:
    def __init__(
        self,
        ffmpeg,
        internal_url=None,
        rtsp_port=None,
        onvif_port=None,
        probe=None,
        publisher_factory=Publisher,
    ):
        self.ffmpeg = ffmpeg
        self.internal_url = (
            internal_url
            or os.environ.get("BRIDGE_RTSP_INTERNAL_URL", "rtsp://127.0.0.1:8554")
        ).rstrip("/")
        parsed = urlsplit(self.internal_url)
        if (
            parsed.scheme != "rtsp"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Invalid internal RTSP service URL")
        self.rtsp_host = parsed.hostname
        self.internal_port = parsed.port or 8554
        self.rtsp_port = int(rtsp_port or os.environ.get("BRIDGE_RTSP_PORT", "8554"))
        self.onvif_port = int(
            onvif_port
            if onvif_port is not None
            else os.environ.get("BRIDGE_ONVIF_PORT", "8899")
        )
        if not 1 <= self.rtsp_port <= 65535 or not 0 <= self.onvif_port <= 65535:
            raise ValueError("Invalid export port")
        self.probe = probe or self._probe
        self.publisher_factory = publisher_factory
        self.lock = threading.RLock()
        self.entries = {}
        self.generations = weakref.WeakKeyDictionary()
        self.closed = False
        self.publisher_password = secrets.token_urlsafe(32)
        self.onvif_server = None
        self.discovery = None
        self.onvif_lock = threading.Lock()
        self.events = EventBroker()
        from .archive import ArchiveManager
        from .onvif_archive import ArchiveSearch

        self.archive = ArchiveManager(self)
        self.searches = ArchiveSearch()

    def _probe(self):
        try:
            with socket.create_connection(
                (self.rtsp_host, self.internal_port), timeout=1
            ):
                return True
        except OSError:
            return False

    def _host(self, workspace, camera_id, value):
        if value:
            if (
                not isinstance(value, str)
                or len(value) > 253
                or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value)
            ):
                raise ExportError("invalid_advertise_host")
            return value
        with workspace.lock:
            ip = workspace.records[camera_id].ip
        if not ip:
            raise ExportError("camera_ip_required")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((ip, 9))
                return sock.getsockname()[0]
        except OSError:
            raise ExportError("advertise_host_required") from None

    def _ensure_onvif(self):
        with self.onvif_lock:
            if self.onvif_server:
                return
            from .onvif import ONVIFServer, DiscoveryService

            try:
                server = ONVIFServer(
                    (os.environ.get("BRIDGE_ONVIF_LISTEN", "0.0.0.0"), self.onvif_port),
                    self,
                )
            except OSError:
                raise ExportError("onvif_port_unavailable") from None
            self.onvif_port = server.server_address[1]
            self.onvif_server = server
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.discovery = DiscoveryService(self)
            self.discovery.start()

    def _find(self, workspace, camera_id):
        with self.lock:
            return next(
                (
                    e
                    for e in self.entries.values()
                    if e.workspace is workspace and e.camera_id == camera_id
                ),
                None,
            )

    def has_workspace(self, workspace):
        with self.lock:
            return any(e.workspace is workspace for e in self.entries.values())

    def configure(self, workspace, camera_id, data):
        if not isinstance(data, dict) or type(data.get("enabled")) is not bool:
            raise ExportError("invalid_export_settings")
        with workspace.lock:
            if workspace.closed:
                raise ExportError("session_expired")
            if camera_id not in workspace.records:
                raise KeyError(camera_id)
        if not data["enabled"]:
            self.disable(workspace, camera_id)
            return {"enabled": False, "available": True}
        for flag in ("rtsp", "onvif"):
            if flag in data and type(data[flag]) is not bool:
                raise ExportError("invalid_export_settings")
        onvif = data.get("onvif", True)
        if not onvif and not data.get("rtsp", True):
            raise ExportError("invalid_export_settings")
        with workspace.lock:
            if camera_id not in workspace.cameras:
                raise ExportError("camera_not_streaming")
            expected_camera = workspace.cameras[camera_id]
        with self.lock:
            generations = self.generations.setdefault(workspace, {})
            generation = generations.get(camera_id, 0) + 1
            generations[camera_id] = generation
        host = self._host(workspace, camera_id, data.get("advertise_host"))
        if not self.probe():
            raise ExportError("rtsp_service_unavailable")
        if onvif:
            self._ensure_onvif()
        entry = Publication(
            workspace, camera_id, "e" + secrets.token_hex(10), host, onvif
        )
        with workspace.lock:
            with self.lock:
                if self.closed:
                    raise ExportError("bridge_stopped")
                if workspace.closed:
                    raise ExportError("session_expired")
                if self.generations.get(workspace, {}).get(camera_id) != generation:
                    raise ExportError("export_superseded")
                if workspace.cameras.get(camera_id) is not expected_camera:
                    raise ExportError("export_superseded")
                previous = [
                    e
                    for e in self.entries.values()
                    if e.workspace is workspace and e.camera_id == camera_id
                ]
                if len(self.entries) - len(previous) >= 32:
                    raise ExportError("too_many_exports")
                for old in previous:
                    old.stop.set()
                    self.entries.pop(old.export_id, None)
                self.entries[entry.export_id] = entry
        self._stop_entries(previous)
        entry.motion = MotionController(lambda: self._camera(entry))
        if entry.onvif:
            entry.event_thread = threading.Thread(
                target=self._observe_events, args=(entry,), daemon=True
            )
            entry.event_thread.start()
        entry.thread = threading.Thread(
            target=self._supervise, args=(entry,), daemon=True
        )
        entry.thread.start()
        return self.status(workspace, camera_id)

    def _camera(self, entry):
        with entry.workspace.lock:
            return entry.workspace.cameras.get(entry.camera_id)

    def _supervise(self, entry):
        while not entry.stop.is_set():
            camera = self._camera(entry)
            if camera:
                lenses = camera.status().get("lenses", [0])
                for lens in lenses:
                    if type(lens) is not int or not 0 <= lens <= 15:
                        continue
                    with entry.lock:
                        old = entry.publishers.get(lens)
                        if old and old.camera is camera:
                            continue
                        if old:
                            old.stop()
                            old.join()
                        if entry.stop.is_set():
                            break
                        path = f"{entry.export_id}/lens{lens}"
                        url = (
                            self.internal_url.replace(
                                "rtsp://",
                                "rtsp://publish:" + self.publisher_password + "@",
                                1,
                            )
                            + "/"
                            + path
                        )
                        worker = self.publisher_factory(camera, lens, self.ffmpeg, url)
                        entry.publishers[lens] = worker
                        worker.start()
            entry.stop.wait(0.5)

    def _view(self, entry, private=False):
        camera = self._camera(entry)
        with entry.workspace.lock:
            record = entry.workspace.records.get(entry.camera_id)
            name = record.device.name if record else "Bridge camera"
        status = camera.status() if camera else {}
        metadata = {x.get("id"): x for x in status.get("lens_metadata", [])}
        profiles = []
        for lens in status.get("lenses", [0]):
            if type(lens) is not int or not 0 <= lens <= 15:
                continue
            meta = metadata.get(lens, {})
            profiles.append(
                {
                    "lens": lens,
                    "token": "lens" + str(lens),
                    "width": meta.get("width", 1920),
                    "height": meta.get("height", 1080),
                    "fps": meta.get("reported_fps", 10),
                    "rtsp_uri": f"rtsp://{entry.host}:{self.rtsp_port}/{entry.export_id}/lens{lens}",
                    "snapshot_uri": f"http://{entry.host}:{self.onvif_port}/onvif/{entry.export_id}/snapshot.jpg?lens={lens}",
                }
            )
        with entry.lock:
            workers = list(entry.publishers.values())
        error = next((w.error for w in workers if w.error), None)
        result = {
            "enabled": True,
            "available": True,
            "export_id": entry.export_id,
            "camera_id": entry.camera_id,
            "name": name,
            "advertise_host": entry.host,
            "rtsp_port": self.rtsp_port,
            "onvif_port": self.onvif_port,
            "rtsp": True,
            "onvif": entry.onvif,
            "ptz": bool(status.get("metadata", {}).get("motor")),
            "audio": dict(status.get("audio", {})),
            "events": bool(entry.onvif),
            "recording": bool(entry.onvif),
            "state": (
                "waiting"
                if not camera
                else (
                    "error"
                    if error
                    else (
                        "streaming"
                        if workers and all(w.written for w in workers)
                        else "starting"
                    )
                )
            ),
            "error": error,
            "profiles": profiles,
            "onvif_uri": (
                f"http://{entry.host}:{self.onvif_port}/onvif/{entry.export_id}/device_service"
                if entry.onvif
                else None
            ),
            "discovery_error": (
                getattr(self.discovery, "error", None) if entry.onvif else None
            ),
        }
        if private:
            result.update(username="bridge", password=entry.password)
        return result

    def status(self, workspace, camera_id):
        with workspace.lock:
            if camera_id not in workspace.records:
                raise KeyError(camera_id)
        entry = self._find(workspace, camera_id)
        if entry:
            return self._view(entry)
        available = self.probe()
        return {
            "enabled": False,
            "available": available,
            "reason": None if available else "rtsp_service_unavailable",
        }

    def credentials(self, workspace, camera_id):
        entry = self._find(workspace, camera_id)
        if not entry:
            raise ExportError("export_not_enabled")
        return {"username": "bridge", "password": entry.password}

    def get_export(self, export_id):
        with self.lock:
            entry = self.entries.get(export_id)
        return (
            self._view(entry, private=True)
            if entry and entry.onvif and not entry.stop.is_set()
            else None
        )

    def list_exports(self):
        with self.lock:
            entries = list(self.entries.values())
        return [
            self._view(e, private=True)
            for e in entries
            if e.onvif and not e.stop.is_set()
        ]

    def _observe_events(self, entry):
        while not entry.stop.is_set():
            camera = self._camera(entry)
            if camera:
                try:
                    result = camera.control("query", {"section": "status"})
                    if entry.stop.is_set():
                        break
                    values = result.get("parameters", {})
                    alarm = values.get("alarm_status")
                    if alarm is not None and str(alarm).lstrip("-").isdigit():
                        alarm = int(alarm)
                        if alarm != entry.alarm_state:
                            # Preserve the native code; do not invent a motion interpretation.
                            self.events.publish(
                                entry.export_id,
                                "tns1:Device/Trigger/Alarm",
                                {"rawAlarm": "alarm_status"},
                                {"State": str(alarm)},
                            )
                            entry.alarm_state = alarm
                    for key in ("motion_detected", "motion_alarm", "is_motion"):
                        if key in values and str(values[key]) in ("0", "1"):
                            state = str(values[key]) == "1"
                            previous = getattr(entry, "motion_observation", None)
                            if previous is not state:
                                self.events.publish(
                                    entry.export_id,
                                    "tns1:VideoSource/MotionAlarm",
                                    {"VideoSourceConfigurationToken": "lens0"},
                                    {"IsMotion": str(state).lower()},
                                )
                                entry.motion_observation = state
                            break
                except (ValueError, OSError):
                    pass
            entry.stop.wait(2)

    def ptz(self, export_id, profile_token, operation, parameters):
        with self.lock:
            entry = self.entries.get(export_id)
        if not entry or entry.stop.is_set():
            raise ValueError("export_not_enabled")
        view = self._view(entry)
        if not view["ptz"]:
            raise ValueError("ptz_not_supported")
        profile = next(
            (p for p in view["profiles"] if p["token"] == profile_token), None
        )
        if profile is None:
            raise ValueError("invalid_profile")
        motion = entry.motion
        if operation == "continuous_move":
            motion.move(
                profile["lens"],
                parameters["x"],
                parameters["y"],
                parameters.get("timeout", 0.6),
            )
            return {}
        if operation == "stop":
            motion.stop(force=True)
            return {}
        if operation == "status":
            return {"moving": motion.moving()}
        if operation in ("get_presets", "set_preset", "goto_preset", "remove_preset"):
            return motion.preset(
                operation, parameters.get("slot"), parameters.get("name")
            )
        raise ValueError("unsupported_ptz_operation")

    def archive_records(self, export_id):
        return self.archive.records(export_id)

    def archive_replay(self, export_id, token):
        return self.archive.replay(export_id, token)

    def snapshot(self, export_id, lens):
        with self.lock:
            entry = self.entries.get(export_id)
        if not entry or entry.stop.is_set():
            raise KeyError(export_id)
        camera = self._camera(entry)
        if camera is None:
            raise ExportError("camera_not_streaming")
        if lens not in camera.status().get("lenses", []):
            raise KeyError(lens)
        frames = camera.frames("jpeg", lens=lens)
        try:
            frame = next(frames, None)
            if not frame:
                raise ExportError("snapshot_unavailable")
            return frame
        finally:
            frames.close()

    def authenticate(self, data):
        if not isinstance(data, dict) or data.get("protocol") != "rtsp":
            return False
        path = data.get("path")
        user = data.get("user")
        password = data.get("password")
        action = data.get("action")
        if (
            not all(isinstance(x, str) for x in (path, user, password))
            or len(path) > 128
            or len(password) > 512
        ):
            return False
        match = re.fullmatch(r"(e[0-9a-f]{20})/lens(\d{1,2})", path)
        replay = re.fullmatch(r"(e[0-9a-f]{20})/replay/([A-Za-z0-9_-]{16,64})", path)
        if not match and not replay:
            return False
        target = match or replay
        with self.lock:
            entry = self.entries.get(target[1])
        if not entry or entry.stop.is_set():
            return False
        camera = self._camera(entry)
        if (
            not camera
            or (match and int(match[2]) not in camera.status().get("lenses", []))
            or (replay and not self.archive.replay_allowed(replay[1], replay[2]))
        ):
            return False
        if action == "publish":
            return user == "publish" and hmac.compare_digest(
                password, self.publisher_password
            )
        if action == "read":
            return user == "bridge" and hmac.compare_digest(password, entry.password)
        return False

    def disable(self, workspace, camera_id=None):
        with self.lock:
            generations = self.generations.setdefault(workspace, {})
            targets = list(generations) if camera_id is None else [camera_id]
            for target in targets:
                generations[target] = generations.get(target, 0) + 1
            entries = [
                e
                for e in self.entries.values()
                if e.workspace is workspace
                and (camera_id is None or e.camera_id == camera_id)
            ]
            for entry in entries:
                entry.stop.set()
                self.entries.pop(entry.export_id, None)
        self._stop_entries(entries)

    def _stop_entries(self, entries):
        for entry in entries:
            self.events.drop(entry.export_id)
            self.searches.drop(entry.export_id)
            self.archive.drop(entry)
            if entry.motion:
                try:
                    entry.motion.stop()
                except (ValueError, OSError):
                    pass
            if entry.event_thread:
                entry.event_thread.join(timeout=13)
            with entry.lock:
                workers = list(entry.publishers.values())
            for worker in workers:
                worker.stop()
            for worker in workers:
                worker.join()
            if entry.thread:
                entry.thread.join(timeout=2)

    def close(self):
        with self.lock:
            self.closed = True
            workspaces = {e.workspace for e in self.entries.values()}
        for workspace in workspaces:
            self.disable(workspace)
        self.archive.close()
        with self.onvif_lock:
            if self.discovery:
                self.discovery.close()
            if self.onvif_server:
                self.onvif_server.shutdown()
                self.onvif_server.server_close()
