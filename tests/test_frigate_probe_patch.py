import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "patch_probes", Path("integrations/frigate/patch_probes.py")
)
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


class ProbePatchTests(unittest.TestCase):
    def test_tcp_probe_is_bounded_and_idempotent(self):
        source = """def ffprobe_stream(ffmpeg, path, detailed=False):
    clean_path=path
    def run(rtsp_transport=None):
        cmd = [ffmpeg.ffprobe_path]
        return rtsp_transport,cmd
    result = run()
    return result
"""
        updated = patch.patch_function(source, "ffprobe_stream", patch.probe)
        self.assertEqual(
            updated, patch.patch_function(updated, "ffprobe_stream", patch.probe)
        )
        namespace = {}
        exec(updated, namespace)
        from types import SimpleNamespace

        transport, command = namespace["ffprobe_stream"](
            SimpleNamespace(ffprobe_path="ffprobe"), "rtsp://fixture"
        )
        self.assertEqual(transport, "tcp")
        self.assertIn("500000", command)
        transport, command = namespace["ffprobe_stream"](
            SimpleNamespace(ffprobe_path="ffprobe"), "file.mkv"
        )
        self.assertIsNone(transport)
        self.assertEqual(command, ["ffprobe"])

    def test_changed_upstream_layout_fails_instead_of_guessing(self):
        with self.assertRaises(ValueError):
            patch.probe("def ffprobe_stream():\n    return None\n")
