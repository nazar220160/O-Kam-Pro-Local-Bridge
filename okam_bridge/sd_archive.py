"""Read-only SD retrieval over the camera's selected transport in its own session."""

import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .transport import (
    authenticate,
    authorize_account,
    connect_camera,
    make_request,
    response_result,
)
from .vendor.cs2 import CS2Error, CS2Timeout, read_command, write_command

MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAGIC = b"\x55\xaa\x15\xa8"


def _iso(stamp):
    return (
        datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace("+00:00", "Z")
    )


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError("SD date must be YYYYMMDD")
    datetime.strptime(value, "%Y%m%d")
    return value


def _cancelled(cancel):
    return cancel is not None and (
        cancel.is_set() if hasattr(cancel, "is_set") else cancel()
    )


def parse_dates(payload):
    """Parse only the known legacy array assignment, never CGI JavaScript."""
    if len(payload) > 65535:
        raise ValueError("SD date response too large")
    values = re.findall(
        rb"\brecord_date\s*\[\s*([0-9]{1,4})\s*\]\s*=\s*['\"]?([0-9]{8})(?![0-9])",
        payload,
    )
    result = set()
    for _, date in values[:4096]:
        try:
            result.add(_date(date.decode("ascii")))
        except ValueError:
            continue
    return sorted(result)


def parse_index(data):
    """Decode the VSDK's fixed eight-byte header/keyframe/footer records."""
    if len(data) > MAX_INDEX_BYTES or len(data) % 8:
        raise ValueError("Invalid SD timeline index length")
    records = []
    offset = 0
    while offset < len(data):
        kind, stamp, count, interval = struct.unpack_from("<BIHB", data, offset)
        offset += 8
        if kind & 3:
            raise ValueError("Invalid SD timeline header")
        event = kind >> 2
        if count > (len(data) - offset) // 8 - 1:
            raise ValueError("Incomplete SD timeline entry")
        frames = []
        for _ in range(count):
            typ, timestamp, number, gop = struct.unpack_from("<BIHB", data, offset)
            offset += 8
            if typ & 3 != 1:
                raise ValueError("Invalid SD keyframe entry")
            if frames and timestamp < frames[-1]["timestamp"]:
                raise ValueError("Non-monotonic SD keyframes")
            frames.append({"timestamp": timestamp, "frame_no": number, "gop": gop})
            if gop == 45:
                interval = 3
        typ, end, final_count, _ = struct.unpack_from("<BIHB", data, offset)
        offset += 8
        if typ & 3 != 2 or not frames or end <= frames[0]["timestamp"]:
            raise ValueError("Invalid SD timeline footer")
        if frames[-1]["timestamp"] > end:
            raise ValueError("SD keyframe outside recording")
        date = datetime.fromtimestamp(stamp, timezone.utc)
        code = "100" if event == 0 else f"{event + 9:03d}"
        identity = hashlib.sha256(f"{stamp}:{event}".encode("ascii")).hexdigest()
        records.append(
            {
                "id": identity,
                "filename": date.strftime("%Y%m%d%H%M%S") + "_" + code + ".mp4",
                "timestamp": stamp,
                "event": event,
                "start": _iso(frames[0]["timestamp"]),
                "end": _iso(end),
                "duration": end - frames[0]["timestamp"],
                "keyframes": frames,
                "frame_interval": interval,
                "frame_count": final_count,
                "source": "sd",
            }
        )
    return records


def parse_frame_header(header):
    if len(header) != 32 or header[:4] != MAGIC:
        raise ValueError("Invalid SD playback frame header")
    size = int.from_bytes(header[16:20], "little")
    lens = int.from_bytes(header[26:28], "little")
    if size > MAX_FRAME_BYTES or lens > 15:
        raise ValueError("Invalid SD playback frame bounds")
    return {
        "type": header[4],
        "size": size,
        "lens": lens,
        "fps": int.from_bytes(header[28:30], "little"),
        "seconds": int.from_bytes(header[8:12], "little"),
        "sequence": int.from_bytes(header[12:16], "little"),
    }


def iter_frames(data, allow_incomplete=False):
    """Offline diagnostic decoder; partial final capture data is never emitted."""
    offset = 0
    while offset < len(data):
        if len(data) - offset < 32:
            if allow_incomplete:
                return
            raise ValueError("Incomplete SD playback header")
        frame = parse_frame_header(data[offset : offset + 32])
        offset += 32
        if offset + frame["size"] > len(data):
            if allow_incomplete:
                return
            raise ValueError("Incomplete SD playback payload")
        yield frame, data[offset : offset + frame["size"]]
        offset += frame["size"]


class SDSession:
    """A session owned exclusively by one archive operation."""

    def __init__(self, config):
        self.config = config
        self.session = None
        self._heartbeat = time.monotonic()

    def __enter__(self):
        self.session = connect_camera(self.config)
        try:
            authenticate(self.session, self.config)
            authorize_account(self.session, self.config)
        except BaseException:
            self.session.close()
            raise
        return self

    def __exit__(self, *args):
        self.session.close()

    def send(self, path):
        c = self.config
        write_command(
            self.session,
            make_request(
                path if path.endswith("&") else path + "&",
                c.get("username", "admin"),
                c["password"],
                c.get("compatibility_password"),
                account_id=c.get("account_id"),
            ),
        )

    def request(self, path, command, timeout=8, allow_empty=False):
        self.send(path)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                cmd, payload = read_command(
                    self.session, timeout=max(0.01, deadline - time.monotonic())
                )
            except CS2Timeout:
                if allow_empty:
                    return None
                raise
            if cmd == command:
                result = response_result(payload[:512])
                if result is not None and result != 0:
                    raise CS2Error("SD archive command rejected")
                return payload
        if not allow_empty:
            raise CS2Timeout("SD archive response timed out")
        return None

    def read(self, count, deadline, cancel):
        while time.monotonic() < deadline:
            if _cancelled(cancel):
                raise InterruptedError("SD archive download cancelled")
            if time.monotonic() - self._heartbeat >= 10:
                self.request(
                    "get_status.cgi?name=admin&", 24577, timeout=1, allow_empty=True
                )
                self._heartbeat = time.monotonic()
            try:
                return self.session.read_exact(
                    4, count, timeout=min(1, max(0.01, deadline - time.monotonic()))
                )
            except CS2Timeout:
                # read_exact retains incomplete bytes; retry the same boundary.
                continue
        raise CS2Timeout("SD archive download timed out")


class SDArchive:
    def __init__(self, config, ffmpeg="ffmpeg"):
        self.config = dict(config)
        self.ffmpeg = str(ffmpeg)
        sibling = Path(self.ffmpeg).with_name("ffprobe")
        self.ffprobe = str(sibling) if sibling.exists() else "ffprobe"

    def list_dates(self):
        with SDSession(self.config) as session:
            return parse_dates(
                session.request("get_record_file.cgi?GetType=date&", 24583)
            )

    def list_records(self, date):
        date = _date(date)
        data = bytearray()
        with SDSession(self.config) as session:
            for page in range(128):
                payload = session.request(
                    f"get_record_idx.cgi?dirname={date}&offset={page}&", 24833
                )
                if len(payload) < 12 or response_result(payload[:12]) != 0:
                    raise ValueError("Invalid SD timeline response")
                data.extend(payload[12:])
                if len(data) > MAX_INDEX_BYTES:
                    raise ValueError("SD timeline index too large")
                if len(payload) != 60012:
                    return parse_index(data)
        raise ValueError("SD timeline page limit exceeded")

    def fetch(self, record, directory, max_seconds=300, cancel=None):
        if not isinstance(record, dict) or record.get("source") != "sd":
            raise ValueError("Invalid SD archive record")
        stamp, event = record.get("timestamp"), record.get("event")
        if (
            type(stamp) is not int
            or not 0 <= stamp <= 0xFFFFFFFF
            or type(event) is not int
            or not 0 <= event <= 63
        ):
            raise ValueError("Invalid SD playback selection")
        if (
            isinstance(max_seconds, bool)
            or not isinstance(max_seconds, (float, int))
            or not math.isfinite(max_seconds)
            or not 0 < max_seconds <= 300
        ):
            raise ValueError("SD clip duration must be 0–300 seconds")
        start = datetime.fromisoformat(record["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(record["end"].replace("Z", "+00:00"))
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("Invalid SD recording interval")
        limit = min(float(max_seconds), (end - start).total_seconds())
        directory = Path(directory).absolute()
        if directory.is_symlink():
            raise ValueError("Unsafe SD output directory")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if shutil.disk_usage(directory).free < MAX_DOWNLOAD_BYTES + 16 * 1024 * 1024:
            raise ValueError("Insufficient disk space for SD download")
        paths, handles, metadata, outputs = {}, {}, {}, []
        token = hashlib.sha256(
            f"{stamp}:{event}:{uuid.uuid4().hex}".encode()
        ).hexdigest()
        total = 0
        try:
            with SDSession(self.config) as session:
                try:
                    if _cancelled(cancel):
                        raise InterruptedError("SD archive download cancelled")
                    session.request(
                        f"livestream.cgi?streamid=5&ntsamp={stamp}&event={event}&framenum=0&recch=4&key=0&",
                        24631,
                        timeout=2,
                        allow_empty=True,
                    )
                    deadline = time.monotonic() + limit + 10
                    while True:
                        header = parse_frame_header(session.read(32, deadline, cancel))
                        size = header["size"]
                        total += size + 32
                        if total > MAX_DOWNLOAD_BYTES:
                            raise ValueError("SD download size limit exceeded")
                        payload = session.read(size, deadline, cancel) if size else b""
                        if header["type"] not in (0, 1) or not payload:
                            continue
                        # Observed types 0/1 carry Annex B H.264; type 13 is audio.
                        if not re.search(rb"\x00\x00(?:\x00)?\x01[\x01-\x7f]", payload):
                            continue
                        lens = header["lens"]
                        if lens not in handles:
                            if header["type"] != 0:
                                continue  # Begin each independent sensor at a keyframe.
                            path = directory / f"{token}-{lens}.part.h264"
                            fd = os.open(
                                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                            )
                            handles[lens] = os.fdopen(fd, "wb")
                            paths[lens] = path
                            fps = header["fps"] if 1 <= header["fps"] <= 60 else 10
                            metadata[lens] = {"fps": fps, "frames": 0}
                        meta = metadata[lens]
                        if meta["frames"] < math.ceil(limit * meta["fps"]):
                            handles[lens].write(payload)
                            meta["frames"] += 1
                        if header["sequence"] >= math.ceil(limit * meta["fps"]) and all(
                            m["frames"] >= math.ceil(limit * m["fps"])
                            for m in metadata.values()
                        ):
                            break
                except CS2Timeout:
                    # A camera may stop transmitting at the recording boundary.
                    # Only complete frames are retained; an empty result still fails.
                    if not metadata:
                        raise
                finally:
                    # Attempt native stop even on cancellation or malformed media.
                    try:
                        session.send("livestream.cgi?streamid=17&")
                    except (CS2Error, OSError):
                        pass
            for handle in handles.values():
                handle.close()
            if not metadata:
                raise ValueError("SD playback returned no H.264 video")
            env = dict(os.environ)
            env.pop("FFREPORT", None)
            for lens, path in paths.items():
                if _cancelled(cancel):
                    raise InterruptedError("SD archive download cancelled")
                destination = directory / f"{token}-{lens}.mkv"
                # Reserve the path ourselves, so FFmpeg cannot overwrite an existing file.
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
                outputs.append(destination)
                result = subprocess.run(
                    [
                        self.ffmpeg,
                        "-nostdin",
                        "-v",
                        "error",
                        "-y",
                        "-r",
                        str(metadata[lens]["fps"]),
                        "-f",
                        "h264",
                        "-i",
                        str(path),
                        "-c:v",
                        "copy",
                        "-bsf:v",
                        f"setts=pts=N/({metadata[lens]['fps']}*TB):dts=N/({metadata[lens]['fps']}*TB)",
                        "-an",
                        str(destination),
                    ],
                    capture_output=True,
                    timeout=45,
                    env=env,
                )
                if result.returncode:
                    raise ValueError("SD video remux failed")
                probe = subprocess.run(
                    [
                        self.ffprobe,
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration:stream=codec_type",
                        "-of",
                        "json",
                        str(destination),
                    ],
                    capture_output=True,
                    timeout=10,
                    env=env,
                )
                try:
                    info = json.loads(probe.stdout)
                    duration = float(info["format"]["duration"])
                    if (
                        probe.returncode
                        or not math.isfinite(duration)
                        or not 0 < duration <= limit + 1
                        or not any(
                            s.get("codec_type") == "video"
                            for s in info.get("streams", [])
                        )
                    ):
                        raise ValueError()
                except (ValueError, KeyError, TypeError):
                    raise ValueError("SD video validation failed") from None
                metadata[lens]["duration"] = duration
            return [
                {
                    "path": str(path),
                    "lens": lens,
                    "start": _iso(start.timestamp()),
                    "end": _iso(start.timestamp() + metadata[lens]["duration"]),
                    "source": "sd",
                }
                for lens, path in zip(paths, outputs)
            ]
        except BaseException:
            for path in outputs:
                path.unlink(missing_ok=True)
            raise
        finally:
            for handle in handles.values():
                handle.close()
            for path in paths.values():
                path.unlink(missing_ok=True)
