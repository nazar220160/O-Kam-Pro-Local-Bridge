"""Allowlisted device metadata and optional local H.264 source probing."""

import json
from pathlib import Path
import re
import shutil
import subprocess

FIELDS = {
    "camera_type": "camera_type",
    "devicetype": "device_type",
    "devicesubtype": "device_subtype",
    "sys_ver": "firmware",
    "app_version": "application_version",
    "cameraMode": "camera_mode",
    "dev_sensor_num": "reported_lenses",
    "haveMic": "microphone",
    "haveHorn": "speaker",
    "haveMotor": "motor",
    "support_g711a": "audio_g711",
    "now": "camera_time",
    "internet": "internet_status",
    "p2pstatus": "p2p_status",
}
BOOLS = {"microphone", "speaker", "motor", "audio_g711"}


def camera_status_metadata(payload):
    result = {}
    text = payload.decode("utf-8", errors="replace")
    for source, target in FIELDS.items():
        match = re.search(
            r"\bvar\s+"
            + re.escape(source)
            + r'\s*=\s*(?:"([^"\r\n]*)"|\x27([^\x27\r\n]*)\x27|([^;\r\n]+))',
            text,
        )
        if not match:
            continue
        value = next((v for v in match.groups() if v is not None), "").strip()[:200]
        if re.fullmatch(r"-?\d+", value):
            value = int(value)
        if target in BOOLS:
            if value not in (0, 1):
                continue
            value = bool(value)
        result[target] = value
    return result


def frame_fps(header):
    if len(header) < 30:
        return None
    value = int.from_bytes(header[28:30], "little")
    return value if 1 <= value <= 120 else None


def probe_h264(ffmpeg, data):
    probe = shutil.which("ffprobe")
    if not probe:
        candidate = Path(ffmpeg).with_name(
            "ffprobe.exe" if Path(ffmpeg).suffix == ".exe" else "ffprobe"
        )
        if candidate.is_file():
            probe = str(candidate)
    if not probe:
        return {}
    try:
        output = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-f",
                "h264",
                "-i",
                "pipe:0",
                "-show_entries",
                "stream=codec_name,width,height",
                "-of",
                "json",
            ],
            input=data[: 4 * 1024 * 1024],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=4,
            check=True,
        )
        stream = json.loads(output.stdout)["streams"][0]
        width, height = stream.get("width"), stream.get("height")
        if (
            type(width) is not int
            or type(height) is not int
            or not 1 <= width <= 16384
            or not 1 <= height <= 16384
        ):
            return {}
        return {"codec": "h264", "width": width, "height": height}
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        return {}
