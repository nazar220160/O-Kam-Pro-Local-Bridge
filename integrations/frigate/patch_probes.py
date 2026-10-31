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
