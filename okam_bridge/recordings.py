"""Opt-in local video recording with a private, account-scoped SQLite index."""

import hashlib
import json
import math
import os
import secrets
import select
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def _stamp(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Recording time requires timezone")
        result = value.timestamp()
    elif isinstance(value, str):
        return _stamp(datetime.fromisoformat(value.replace("Z", "+00:00")))
    else:
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Invalid recording time") from exc
    if not math.isfinite(result):
        raise ValueError("Invalid recording time")
    return result


def _iso(value):
    return (
        datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    )


def _scope(owner, camera_id):
    if (
        not isinstance(owner, str)
        or not owner
        or not isinstance(camera_id, str)
        or not camera_id
    ):
        raise ValueError("Recording owner and camera required")
    return hashlib.sha256(
        json.dumps([owner, camera_id], separators=(",", ":")).encode()
    ).hexdigest()


class RecordingStore:
    def __init__(self, rootpath, ffmpeg):
        self.root = Path(rootpath).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.ffmpeg = str(ffmpeg)
        sibling = Path(self.ffmpeg).with_name("ffprobe")
        self.ffprobe = str(sibling) if sibling.exists() else "ffprobe"
        self.lock = threading.RLock()
        manifest = self.root / "manifest.sqlite3"
        if manifest.is_symlink():
            raise ValueError("Unsafe recording manifest")
        self.db = sqlite3.connect(str(manifest), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS recordings (
            token TEXT PRIMARY KEY, scope TEXT NOT NULL, camera_id TEXT NOT NULL,
            source TEXT NOT NULL, lens INTEGER NOT NULL, start REAL NOT NULL,
            end REAL NOT NULL, duration REAL NOT NULL, size INTEGER NOT NULL,
            path TEXT UNIQUE NOT NULL)"""
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS recording_scope_time ON recordings(scope, start)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS policies (scope TEXT PRIMARY KEY, retention_days INTEGER NOT NULL,max_bytes INTEGER NOT NULL)"
        )
        self.db.commit()
        os.chmod(manifest, 0o600)

    def close(self):
        with self.lock:
            self.db.close()

    def policy(self, owner, camera_id):
        with self.lock:
            row = self.db.execute(
                "SELECT retention_days,max_bytes FROM policies WHERE scope=?",
                (_scope(owner, camera_id),),
            ).fetchone()
        return dict(row) if row else {"retention_days": 7, "max_bytes": 10 * 1024**3}

    def set_policy(self, owner, camera_id, retention_days, max_bytes):
        if (
            type(retention_days) is not int
            or not 1 <= retention_days <= 365
            or type(max_bytes) is not int
            or not 1024**2 <= max_bytes <= 1024**4
        ):
            raise ValueError("Invalid recording limits")
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO policies VALUES (?,?,?)",
                (_scope(owner, camera_id), retention_days, max_bytes),
            )

    def directory(self, owner, camera_id):
        directory = self.root / _scope(owner, camera_id)
        if directory.is_symlink():
            raise ValueError("Unsafe recording directory")
        directory.mkdir(mode=0o700, exist_ok=True)
        return directory

    def _path(self, owner, camera_id, path):
        directory = self.directory(owner, camera_id)
        candidate = Path(path).absolute()
        # Only direct regular children of this owner/camera directory are valid.
        # Never resolve a user-controlled symlink into another account's files.
        if (
            candidate.parent != directory
            or candidate.is_symlink()
            or not candidate.is_file()
        ):
            raise ValueError("Unsafe recording file")
        if candidate.resolve().parent != directory:
            raise ValueError("Unsafe recording file")
        return candidate

    def probe(self, path):
        try:
            result = subprocess.run(
                [
                    self.ffprobe,
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-format_whitelist",
                    "matroska,webm,mov,mp4,m4a,3gp,3g2,mj2,mpegts,avi,h264",
                    "-show_entries",
                    "format=duration:stream=codec_type",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                timeout=10,
                check=True,
                env=self._environment(),
            )
            data = json.loads(result.stdout)
            duration = float(data["format"]["duration"])
            if (
                not math.isfinite(duration)
                or duration <= 0
                or not any(
                    stream.get("codec_type") == "video"
                    for stream in data.get("streams", [])
                )
            ):
                raise ValueError("No complete video recording")
            return duration
        except (
            OSError,
            subprocess.SubprocessError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError("Recording validation failed") from exc

    @staticmethod
    def _environment():
        env = dict(os.environ)
        env.pop("FFREPORT", None)
        return env

    def add_recording(
        self, owner, camera_id, path, source="server", lens=0, start=None, end=None
    ):
        if source not in ("server", "sd") or type(lens) is not int or lens < 0:
            raise ValueError("Invalid recording metadata")
        path = self._path(owner, camera_id, path)
        if path.stat().st_size == 0 or ".part." in path.name:
            raise ValueError("Recording is incomplete")
        duration = self.probe(path)
        start_time = _stamp(start)
        end_time = _stamp(end) if end is not None else start_time + duration
        if end_time <= start_time:
            raise ValueError("Invalid recording interval")
        # Probe first; only a fully closed, probeable file reaches the manifest.
        path = self._path(owner, camera_id, path)
        token = secrets.token_urlsafe(24)
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO recordings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    token,
                    _scope(owner, camera_id),
                    camera_id,
                    source,
                    lens,
                    start_time,
                    end_time,
                    duration,
                    path.stat().st_size,
                    str(path.relative_to(self.root)),
                ),
            )
        return self.get(owner, camera_id, token, private=False)

    def _public(self, row, private=False):
        value = {
            key: row[key]
            for key in ("token", "camera_id", "source", "lens", "duration", "size")
        }
        value.update(start=_iso(row["start"]), end=_iso(row["end"]))
        if private:
            value["path"] = str(self.root / row["path"])
        return value

    def get(self, owner, camera_id, token, private=True):
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM recordings WHERE scope=? AND token=?",
                (_scope(owner, camera_id), token),
            ).fetchone()
            if row is None:
                return None
            try:
                self._path(owner, camera_id, self.root / row["path"])
            except ValueError:
                return None
            return self._public(row, private)

    def list(self, owner, camera_id, source=None, start=None, end=None):
        clauses, parameters = ["scope=?"], [_scope(owner, camera_id)]
        if source is not None:
            if source not in ("server", "sd"):
                raise ValueError("Invalid recording source")
            clauses.append("source=?")
            parameters.append(source)
        if start is not None:
            clauses.append("end>?")
            parameters.append(_stamp(start))
        if end is not None:
            clauses.append("start<?")
            parameters.append(_stamp(end))
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM recordings WHERE "
                + " AND ".join(clauses)
                + " ORDER BY start, token",
                parameters,
            ).fetchall()
            result = []
            for row in rows:
                try:
                    self._path(owner, camera_id, self.root / row["path"])
                except ValueError:
                    continue
                result.append(self._public(row))
            return result

    def stats(self, owner, camera_id):
        with self.lock:
            row = self.db.execute(
                "SELECT COUNT(*) AS count, COALESCE(SUM(size),0) AS bytes FROM recordings WHERE scope=?",
                (_scope(owner, camera_id),),
            ).fetchone()
            return dict(row)

    def enforce_limits(
        self, owner, camera_id, retention_days=7, max_bytes=10 * 1024**3
    ):
        if (
            not math.isfinite(float(retention_days))
            or retention_days < 0
            or type(max_bytes) is not int
            or max_bytes < 0
        ):
            raise ValueError("Invalid recording limits")
        cutoff = time.time() - retention_days * 86400
        removed = 0
        with self.lock, self.db:
            rows = self.db.execute(
                "SELECT * FROM recordings WHERE scope=? ORDER BY end, token",
                (_scope(owner, camera_id),),
            ).fetchall()
            total = sum(row["size"] for row in rows)
            for row in rows:
                if (
                    row["source"] == "sd" or row["end"] >= cutoff
                ) and total <= max_bytes:
                    continue
                try:
                    path = self._path(owner, camera_id, self.root / row["path"])
                    path.unlink()
                except ValueError:
                    pass  # Stale/symlink entries may be forgotten, never followed.
                except OSError:
                    continue
                self.db.execute(
                    "DELETE FROM recordings WHERE token=? AND scope=?",
                    (row["token"], _scope(owner, camera_id)),
                )
                total -= row["size"]
                removed += 1
        return removed


class Recorder:
    def __init__(
        self,
        camera,
        lens,
        store,
        owner,
        camera_id,
        segment_seconds=60,
        retention_days=7,
        max_bytes=10 * 1024**3,
    ):
        if (
            not math.isfinite(float(segment_seconds))
            or not 5 <= segment_seconds <= 3600
        ):
            raise ValueError("Recording segments must be between 5 and 3600 seconds")
        if (
            not math.isfinite(float(retention_days))
            or retention_days < 0
            or type(max_bytes) is not int
            or max_bytes <= 0
        ):
            raise ValueError("Invalid recording limits")
        if type(lens) is not int or lens < 0:
            raise ValueError("Invalid recording lens")
        _scope(owner, camera_id)
        self.camera, self.lens, self.store = camera, lens, store
        self.owner, self.camera_id = owner, camera_id
        self.segment_seconds, self.retention_days, self.max_bytes = (
            segment_seconds,
            retention_days,
            max_bytes,
        )
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.segment_cancel = None
        self.thread = None
        self.process = None
        self.error = None
        self.completed = 0

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.thread = threading.Thread(
                target=self._run, daemon=True, name="bridge-recorder"
            )
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        with self.lock:
            if self.segment_cancel is not None:
                self.segment_cancel.set()

    def join(self, timeout=15):
        if self.thread:
            self.thread.join(timeout=timeout)

    def status(self):
        with self.lock:
            stats = self.store.stats(self.owner, self.camera_id)
            return {
                "running": bool(self.thread and self.thread.is_alive()),
                "error": self.error,
                "lens": self.lens,
                "segments": stats["count"],
                "bytes": stats["bytes"],
                "completed": self.completed,
                "segment_seconds": self.segment_seconds,
            }

    def _write(self, process, data, cancel):
        remaining = memoryview(data)
        deadline = time.monotonic() + 5
        while remaining:
            if cancel.is_set() or self.stop_event.is_set():
                return False
            if process.poll() is not None or time.monotonic() >= deadline:
                raise BrokenPipeError("Recording writer stalled")
            if not select.select([], [process.stdin], [], 0.1)[1]:
                continue
            try:
                count = os.write(process.stdin.fileno(), remaining)
            except BlockingIOError:
                continue
            if count == 0:
                raise BrokenPipeError("Recording pipe closed")
            remaining = remaining[count:]
        return True

    def _record_segment(self):
        directory = self.store.directory(self.owner, self.camera_id)
        basename = secrets.token_hex(16)
        partial = directory / (basename + ".part.mkv")
        final = directory / (basename + ".mkv")
        cancel = threading.Event()
        with self.lock:
            self.segment_cancel = cancel
            if self.stop_event.is_set():
                cancel.set()
        timer = threading.Timer(self.segment_seconds, cancel.set)
        timer.daemon = True
        frames = process = None
        committed = False
        try:
            metadata = next(
                (
                    entry
                    for entry in self.camera.status().get("lens_metadata", [])
                    if entry.get("id") == self.lens
                ),
                {},
            )
            fps = max(
                1,
                min(
                    60,
                    int(
                        metadata.get("reported_fps")
                        or metadata.get("measured_fps")
                        or 10
                    ),
                ),
            )
            command = [
                self.store.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-fflags",
                "+genpts",
                "-r",
                str(fps),
                "-f",
                "h264",
                "-i",
                "pipe:0",
                "-map",
                "0:v:0",
                "-c:v",
                "copy",
                # Annex B has no container clock. Synthesize a monotonic
                # clock from the same camera FPS used by the live export.
                "-bsf:v",
                f"setts=ts=N/({fps}*TB)",
                "-fs",
                str(self.max_bytes),
                "-f",
                "matroska",
                "-n",
                str(partial),
            ]
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                env=self.store._environment(),
            )
            with self.lock:
                self.process = process
            os.set_blocking(process.stdin.fileno(), False)
            start = time.time()
            timer.start()
            frames = self.camera.frames("h264", lens=self.lens, cancel=cancel)
            written = 0
            for frame in frames:
                if cancel.is_set() or self.stop_event.is_set():
                    break
                if (
                    not isinstance(frame, bytes)
                    or len(frame) > 64 * 1024**2
                    or written + len(frame) > self.max_bytes
                ):
                    raise ValueError("Recording segment exceeds storage limit")
                if not self._write(process, frame, cancel):
                    break
                written += len(frame)
            process.stdin.close()
            try:
                result = process.wait(timeout=5)
            except subprocess.TimeoutExpired as exc:
                raise ValueError("Recording finalization timed out") from exc
            if result != 0 or written == 0:
                raise ValueError("Recording did not finalize")
            duration = self.store.probe(partial)
            partial.rename(final)
            self.store.add_recording(
                self.owner,
                self.camera_id,
                final,
                lens=self.lens,
                start=start,
                end=start + duration,
            )
            committed = True
            with self.lock:
                self.completed += 1
                self.error = None
            self.store.enforce_limits(
                self.owner, self.camera_id, self.retention_days, self.max_bytes
            )
        finally:
            timer.cancel()
            if frames is not None:
                frames.close()
            if process is not None:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
            with self.lock:
                self.process = None
                self.segment_cancel = None
            partial.unlink(missing_ok=True)
            if not committed:
                final.unlink(missing_ok=True)

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.store.enforce_limits(
                    self.owner, self.camera_id, self.retention_days, self.max_bytes
                )
                self._record_segment()
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                with self.lock:
                    self.error = "recording_unavailable"
            # Prevent rapid respawn if a disconnected feed ends immediately.
            if self.stop_event.wait(0.25 if self.error is None else 1):
                break
