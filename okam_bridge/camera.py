"""One reconnecting camera session and JPEG decoder shared by all viewers."""

import os
from collections import deque
from .metadata import frame_fps, probe_h264
from .controls import (
    ControlError,
    ControlJob,
    build_action,
    execute_action,
    parse_variables,
    public_fields,
    capabilities,
)
import queue
import re
import subprocess
import threading
import time
from .transport import (
    connect_lan,
    authenticate,
    authorize_account,
    set_video_quality,
    start_video,
    CameraAuthError,
    CameraStartError,
    make_request,
    read_lens_frame,
)
from .vendor.cs2 import (
    CS2Error,
    read_video_frame,
    write_command,
    make_cgi_request,
    read_command_result,
    LOGIN_RESPONSE_COMMAND,
)


class Subscription:
    def __init__(self, capacity):
        self.queue = queue.Queue(capacity)
        self.closed = False

    def get(self, timeout=10):
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return b""

    def close(self):
        self.closed = True
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self.queue.put_nowait(None)


class Fanout:
    def __init__(self, capacity=32):
        self.capacity = capacity
        self.lock = threading.RLock()
        self.subscribers = set()

    @property
    def count(self):
        with self.lock:
            return len(self.subscribers)

    def subscribe(self):
        s = Subscription(self.capacity)
        with self.lock:
            self.subscribers.add(s)
        return s

    def unsubscribe(self, s):
        with self.lock:
            self.subscribers.discard(s)
        s.close()

    def publish(self, frame):
        with self.lock:
            for s in list(self.subscribers):
                if s.closed:
                    self.subscribers.discard(s)
                    continue
                try:
                    s.queue.put_nowait(frame)
                except queue.Full:
                    # Raw H.264 cannot skip arbitrary interframes. End this
                    # slow subscriber so the client can reconnect at a keyframe.
                    s.close()
                    self.subscribers.discard(s)

    def close(self):
        with self.lock:
            for s in self.subscribers:
                s.close()
            self.subscribers.clear()


class JPEGDecoder:
    def __init__(self, ffmpeg, publish):
        self.publish = publish
        self.close_lock = threading.Lock()
        self.closed = False
        self.process = subprocess.Popen(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-probesize",
                "32768",
                "-analyzeduration",
                "0",
                "-f",
                "h264",
                "-i",
                "pipe:0",
                "-an",
                "-vf",
                "fps=5,scale='min(960,iw)':-2",
                "-q:v",
                "5",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        buffer = bytearray()
        try:
            while True:
                chunk = os.read(self.process.stdout.fileno(), 32768)
                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9", max(start, 0))
                    if start < 0 or end < 0:
                        break
                    self.publish(bytes(buffer[start : end + 2]))
                    del buffer[: end + 2]
                if len(buffer) > 8 * 1024 * 1024:
                    buffer.clear()
        except (OSError, ValueError):
            pass

    def write(self, frame):
        if self.process.poll() is not None:
            raise OSError("decoder exited")
        # Pipe writes can be partial on Windows and for large keyframes.
        data = memoryview(frame)
        while data:
            n = self.process.stdin.write(data)
            if not n:
                raise OSError("decoder pipe closed")
            data = data[n:]

    def close(self):
        with self.close_lock:
            if self.closed:
                return
            self.closed = True
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            self.thread.join(timeout=3)
            self.process.stdin.close()
            self.process.stdout.close()


class GopCache:
    def __init__(self):
        self.sps = self.pps = b""
        self.gop = bytearray()

    def __bool__(self):
        return bool(self.gop)

    def __bytes__(self):
        return bytes(self.gop)

    def clear(self):
        self.sps = self.pps = b""
        self.gop.clear()

    def append(self, data):
        starts = list(re.finditer(rb"\x00\x00(?:\x00)?\x01", data))
        idr = False
        for i, m in enumerate(starts):
            if m.end() >= len(data):
                continue
            nal = data[m.end()] & 31
            part = data[
                m.start() : starts[i + 1].start() if i + 1 < len(starts) else len(data)
            ]
            if nal == 7:
                self.sps = part
            if nal == 8:
                self.pps = part
            if nal == 5:
                idr = True
        if idr:
            prefix = b""
            if self.sps and self.sps not in data:
                prefix += self.sps
            if self.pps and self.pps not in data:
                prefix += self.pps
            self.gop = bytearray(prefix + data)
        elif self.gop:
            self.gop.extend(data)
        if len(self.gop) > 4 * 1024 * 1024:
            self.gop.clear()


class LensMedia:
    def __init__(self):
        self.hubs = {"jpeg": Fanout(8), "h264": Fanout(32)}
        self.jpeg = None
        self.preamble = GopCache()
        self.decoder = None
        self.source = {}
        self.probed = False
        self.probe_sps = b""
        self.probe_version = 0
        self.frames_received = 0
        self.bytes_received = 0
        self.last_frame = None
        self.reported_fps = None
        self.recent = deque(maxlen=600)


class Camera:
    def __init__(self, config, ffmpeg, idle_timeout=30):
        self.config = config
        self.name = config.get("name", config["id"])
        self.ffmpeg = ffmpeg
        self.idle_timeout = idle_timeout
        self.lock = threading.RLock()
        self.lenses = {0: LensMedia()}
        self.observed_lenses = {0}
        self.stop_event = threading.Event()
        self.thread = None
        self.state = "idle"
        self.last_error = None
        self.last_frame = None
        self.session = None
        self.last_viewer = time.monotonic()
        self.connections = 0
        self.metadata = {}
        self.details = {}
        self.control_queue = queue.Queue(8)
        self.control_idle = threading.Event()
        self.control_idle.set()

    def control(self, action, args=None):
        command = build_action(action, args)
        with self.lock:
            if (
                self.stop_event.is_set()
                or self.session is None
                or self.state not in ("streaming", "connecting")
            ):
                raise ControlError("camera_not_streaming")
        job = ControlJob(command)
        try:
            self.control_queue.put_nowait(job)
        except queue.Full:
            raise ControlError("control_busy") from None
        if not job.done.wait(12):
            job.cancel()
            raise ControlError("control_timeout")
        if job.error:
            raise ControlError(job.error)
        return job.result

    def _process_controls(self, session):
        for _ in range(3):
            try:
                job = self.control_queue.get_nowait()
            except queue.Empty:
                return
            if self.stop_event.is_set():
                job.error = "camera_stopped"
                job.done.set()
                continue
            if not job.claim():
                continue
            self.control_idle.clear()
            try:
                job.result = execute_action(
                    session, self.config, job.action, self.stop_event
                )
                if job.action["action"] == "query":
                    with self.lock:
                        self.details[job.action["args"].get("section", "status")] = {
                            "state": job.result["state"],
                            "result": job.result.get("result"),
                            "parameters": job.result.get("parameters", {}),
                        }
            except (CS2Error, OSError, ValueError):
                job.error = "camera_control_failed"
            finally:
                self.control_idle.set()
                job.done.set()

    def inspect(self):
        with self.lock:
            groups = {
                name: dict(value.get("parameters", {}))
                for name, value in self.details.items()
            }
            return {
                "groups": groups,
                "queries": {
                    name: {k: v for k, v in value.items() if k != "parameters"}
                    for name, value in self.details.items()
                },
                "capabilities": capabilities(groups),
            }

    def _cancel_controls(self):
        while True:
            try:
                job = self.control_queue.get_nowait()
            except queue.Empty:
                return
            job.error = "camera_stopped"
            job.cancel()
            job.done.set()

    def _media(self, lens):
        if type(lens) is not int or not 0 <= lens <= 15:
            raise ValueError("Invalid lens index")
        with self.lock:
            if lens not in self.lenses:
                self.lenses[lens] = LensMedia()
            return self.lenses[lens]

    def _viewers(self):
        return sum(h.count for m in self.lenses.values() for h in m.hubs.values())

    def status(self):
        with self.lock:
            return {
                "state": self.state,
                "last_error": self.last_error,
                "viewers": self._viewers(),
                "lenses": sorted(self.observed_lenses),
                "last_frame": self.last_frame,
                "connections": self.connections,
                "metadata": dict(self.metadata),
                "lens_metadata": [
                    self._lens_status(n) for n in sorted(self.observed_lenses)
                ],
            }

    def _lens_status(self, lens):
        media = self.lenses[lens]
        now = time.monotonic()
        recent = [(t, n) for t, n in media.recent if now - t <= 5]
        elapsed = now - recent[0][0] if recent else 0
        measured_fps = (
            round((len(recent) - 1) / elapsed, 1)
            if elapsed >= 1 and len(recent) > 1
            else None
        )
        bitrate = (
            round(sum(n for _, n in recent) * 8 / elapsed / 1000)
            if elapsed >= 1
            else None
        )
        return {
            "id": lens,
            **media.source,
            "reported_fps": media.reported_fps,
            "measured_fps": measured_fps,
            "bitrate_kbps": bitrate,
            "frames_received": media.frames_received,
            "bytes_received": media.bytes_received,
            "last_frame": media.last_frame,
            "preview_width": (
                min(960, media.source.get("width", 960)) if media.jpeg else None
            ),
        }

    def _probe_source(self, lens, preamble, version=None):
        source = probe_h264(self.ffmpeg, preamble)
        with self.lock:
            media = self._media(lens)
            if version is None or media.probe_version == version:
                media.source.update(source)

    def _publish_jpeg(self, lens, frame):
        with self.lock:
            media = self._media(lens)
            media.jpeg = frame
            media.hubs["jpeg"].publish(frame)

    def frames(self, kind, lens=0, cancel=None):
        with self.lock:
            media = self._media(lens)
            hub = media.hubs[kind]
            s = hub.subscribe()
            if kind == "jpeg" and media.jpeg and self.state == "streaming":
                s.queue.put_nowait(media.jpeg)
            elif kind == "h264" and media.preamble:
                s.queue.put_nowait(bytes(media.preamble))
            if self.stop_event.is_set():
                hub.unsubscribe(s)
                return
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()
        deadline = time.monotonic() + 45
        try:
            while not self.stop_event.is_set() and not (cancel and cancel.is_set()):
                data = s.get(0.25 if cancel is not None else 5)
                if data is None:
                    return
                if data:
                    deadline = time.monotonic() + 45
                    yield data
                elif time.monotonic() >= deadline:
                    return
        finally:
            hub.unsubscribe(s)
            with self.lock:
                self.last_viewer = time.monotonic()

    def _wanted(self):
        with self.lock:
            return (
                self._viewers() > 0
                or time.monotonic() - self.last_viewer < self.idle_timeout
            )

    def _clear_decoders(self):
        with self.lock:
            decoders = [m.decoder for m in self.lenses.values() if m.decoder]
            for m in self.lenses.values():
                m.decoder = None
                m.preamble.clear()
                m.jpeg = None
                m.probed = False
                m.probe_sps = b""
                m.probe_version += 1
                m.source.clear()
        for decoder in decoders:
            decoder.close()

    def _run(self):
        backoff = 1
        while not self.stop_event.is_set() and self._wanted():
            session = None
            try:
                with self.lock:
                    self.state = "connecting"
                session = connect_lan(self.config)
                self.session = session
                user, password = authenticate(session, self.config)
                with self.lock:
                    self.metadata = dict(getattr(session, "camera_metadata", {}))
                    self.details["status"] = {
                        "state": "confirmed",
                        "result": 0,
                        "parameters": public_fields(
                            parse_variables(
                                getattr(session, "last_control_payload", b"")
                            ),
                            (
                                self.config.get("password"),
                                self.config.get("account_token"),
                            ),
                        ),
                    }
                authorize_account(session, self.config)
                start_video(
                    session,
                    user,
                    password,
                    self.config.get("substream", 1),
                    self.config.get("compatibility_password"),
                    account_id=self.config.get("account_id"),
                )
                if self.config.get("quality") is not None:
                    set_video_quality(session, self.config, self.config["quality"])
                with self.lock:
                    self.connections += 1
                    self.last_error = None
                keepalive = time.monotonic()
                while not self.stop_event.is_set() and self._wanted():
                    self._process_controls(session)
                    if self.stop_event.is_set():
                        break
                    data, frame_type, lens = read_lens_frame(session, timeout=10)
                    if not re.search(rb"\x00\x00(?:\x00)?\x01[\x01-\x7f]", data):
                        continue
                    with self.lock:
                        self.state = "streaming"
                        self.last_frame = time.time()
                        media = self._media(lens)
                        self.observed_lenses.add(lens)
                        media.preamble.append(data)
                        media.frames_received += 1
                        media.bytes_received += len(data)
                        media.last_frame = time.time()
                        media.recent.append((time.monotonic(), len(data)))
                        media.reported_fps = frame_fps(
                            getattr(session, "last_video_header", b"")
                        )
                        preamble = bytes(media.preamble)
                        sps = media.preamble.sps
                        if (
                            preamble
                            and (not media.probed or sps != media.probe_sps)
                            and (not sps or sps in preamble)
                        ):
                            media.probed = True
                            media.probe_sps = sps
                            media.probe_version += 1
                            threading.Thread(
                                target=self._probe_source,
                                args=(lens, preamble, media.probe_version),
                                daemon=True,
                            ).start()
                        media.hubs["h264"].publish(data)
                        # Each sensor has an independent H.264 decoding state.
                        # Never feed interleaved lenses into one decoder.
                        initial = None
                        if (
                            media.decoder is None
                            and media.hubs["jpeg"].count
                            and media.preamble
                        ):
                            media.decoder = JPEGDecoder(
                                self.ffmpeg,
                                lambda jpeg, n=lens: self._publish_jpeg(n, jpeg),
                            )
                            initial = bytes(media.preamble)
                        decoder = media.decoder
                    if decoder:
                        decoder.write(initial if initial is not None else data)
                    backoff = 1
                    if time.monotonic() - keepalive > 10:
                        write_command(
                            session,
                            make_request(
                                "get_status.cgi?name=admin&",
                                user,
                                password,
                                self.config.get("compatibility_password"),
                                account_id=self.config.get("account_id"),
                            ),
                        )
                        read_command_result(
                            session, (LOGIN_RESPONSE_COMMAND,), timeout=1
                        )
                        keepalive = time.monotonic()
            except CameraStartError as error:
                with self.lock:
                    self.last_error = str(error)
            except CameraAuthError:
                with self.lock:
                    self.last_error = "camera_password_rejected"
            except (CS2Error, OSError, ValueError):
                with self.lock:
                    self.last_error = "camera_unavailable_or_video_interrupted"
            finally:
                if session:
                    session.close()
                self.session = None
                self._clear_decoders()
                with self.lock:
                    self.state = (
                        "reconnecting"
                        if self._wanted() and not self.stop_event.is_set()
                        else "idle"
                    )
            if self.stop_event.is_set() or not self._wanted():
                break
            if self.stop_event.wait(backoff):
                break
            backoff = min(15, backoff * 2)
        with self.lock:
            self.state = "stopped" if self.stop_event.is_set() else "idle"
            self.thread = None
            if not self.stop_event.is_set() and self._viewers():
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()

    def stop(self):
        self.stop_event.set()
        self._cancel_controls()
        self.control_idle.wait(2)
        with self.lock:
            for m in self.lenses.values():
                for h in m.hubs.values():
                    h.close()
        self._clear_decoders()
        if self.session:
            self.session.close()
        if self.thread:
            self.thread.join(timeout=15)
