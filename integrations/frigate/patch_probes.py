"""Bound Frigate RTSP wizard probes below its browser request timeout.

Applied when building an optional Frigate derivative image. Existing runtime
camera FFmpeg commands and non-RTSP probes are not changed. Fail closed on source
layout changes rather than silently patch an unrelated function.
"""

import ast
from pathlib import Path
import sys

MARKER = "# okam-bridge: bounded TCP probe v1"


def patch_function(source, name, transform):
    tree = ast.parse(source)
    node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name
    )
    lines = source.splitlines(keepends=True)
    body = "".join(lines[node.lineno - 1 : node.end_lineno])
    if MARKER in body:
        return source
    body = transform(body)
    ast.parse(body)
    lines[node.lineno - 1 : node.end_lineno] = [body + "\n"]
    result = "".join(lines)
    ast.parse(result)
    return result


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Unsupported Frigate probe source layout")
    return source.replace(old, new, 1)


def probe(body):
    body = replace_once(
        body,
        "cmd = [ffmpeg.ffprobe_path]",
        """cmd = [ffmpeg.ffprobe_path]
        if clean_path.startswith("rtsp://"):
            cmd += ["-analyzeduration", "500000", "-probesize", "100000"]""",
    )
    return replace_once(
        body,
        "    result = run()",
        """    """
        + MARKER
        + """
    if clean_path.startswith("rtsp://"):
        return run(rtsp_transport="tcp")
    result = run()""",
    )


def snapshot(body):
    return replace_once(
        body,
        "    if seek_time is not None:",
        """    """
        + MARKER
        + """
    if input_path.startswith("rtsp://"):
        # A bridge snapshot is already decoded and cached by the owning
        # camera session; avoid waiting for another RTSP keyframe in the wizard.
        from urllib.parse import urlsplit, unquote
        import os
        import re
        parsed = urlsplit(input_path)
        bridge_path = re.fullmatch(r"/(e[0-9a-f]{20})/lens([0-9]{1,2})", parsed.path)
        if bridge_path and codec == "mjpeg" and seek_time is None and height is None:
            import requests
            from requests.auth import HTTPDigestAuth
            host = parsed.hostname
            if ":" in host:
                host = "[" + host + "]"
            port = int(os.environ.get("FRIGATE_OKAM_ONVIF_PORT", "8899"))
            snapshot_url = f"http://{host}:{port}/onvif/{bridge_path[1]}/snapshot.jpg?lens={bridge_path[2]}"
            try:
                with requests.get(snapshot_url, auth=HTTPDigestAuth(unquote(parsed.username or ""), unquote(parsed.password or "")), timeout=(1, 2)) as response:
                    data = response.content
                    if response.status_code == 200 and data.startswith(b"\\xff\\xd8"):
                        return data, ""
            except (requests.RequestException, ValueError):
                pass
            # Leave headroom for the HTTP attempt inside the browser deadline.
            timeout = min(timeout, 4) if timeout else 4
        ffmpeg_cmd += ["-rtsp_transport", "tcp", "-timeout", "5000000",
                       "-analyzeduration", "500000", "-probesize", "100000",
                       "-threads", "1"]
        timeout = min(timeout, 8) if timeout else 8
    if seek_time is not None:""",
    )


def main(root):
    for filename, name, transform in [
        ("services.py", "ffprobe_stream", probe),
        ("image.py", "run_ffmpeg_snapshot", snapshot),
    ]:
        path = Path(root) / filename
        path.write_text(patch_function(path.read_text(), name, transform))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/opt/frigate/frigate/util")
