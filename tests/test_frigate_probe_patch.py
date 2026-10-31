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

    def test_snapshot_uses_tcp_and_stays_below_browser_timeout(self):
        source = """def run_ffmpeg_snapshot(ffmpeg, input_path, codec, seek_time=None, timeout=None):
    ffmpeg_cmd=[]
    if seek_time is not None:
        ffmpeg_cmd += ['-ss',str(seek_time)]
    return ffmpeg_cmd,timeout
"""
        updated = patch.patch_function(source, "run_ffmpeg_snapshot", patch.snapshot)
        self.assertEqual(
            updated,
            patch.patch_function(updated, "run_ffmpeg_snapshot", patch.snapshot),
        )
        namespace = {}
        exec(updated, namespace)
        cmd, timeout = namespace["run_ffmpeg_snapshot"](
            None, "rtsp://fixture", "mjpeg", timeout=10
        )
        self.assertEqual(timeout, 8)
        self.assertIn("tcp", cmd)
        self.assertIn("500000", cmd)
        cmd, timeout = namespace["run_ffmpeg_snapshot"](
            None, "file.mp4", "mjpeg", timeout=10
        )
        self.assertEqual((cmd, timeout), ([], 10))

    def test_bridge_snapshot_uses_authenticated_cached_jpeg(self):
        from unittest.mock import Mock, patch as mock_patch
        from types import SimpleNamespace

        source = """def run_ffmpeg_snapshot(ffmpeg, input_path, codec, seek_time=None, height=None, timeout=None):
    ffmpeg_cmd=[]
    if seek_time is not None:
        pass
    return ffmpeg_cmd,timeout
"""
        namespace = {}
        exec(
            patch.patch_function(source, "run_ffmpeg_snapshot", patch.snapshot),
            namespace,
        )
        response = Mock()
        response.status_code = 200
        response.content = b"\xff\xd8fixture"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        get = Mock(return_value=response)
        modules = {
            "requests": SimpleNamespace(get=get, RequestException=RuntimeError),
            "requests.auth": SimpleNamespace(
                HTTPDigestAuth=lambda user, pwd: (user, pwd)
            ),
        }
        with mock_patch.dict("sys.modules", modules):
            data, error = namespace["run_ffmpeg_snapshot"](
                None,
                "rtsp://bridge:fixture@camera:8557/e01234567890123456789/lens2",
                "mjpeg",
                timeout=10,
            )
        self.assertEqual((data, error), (b"\xff\xd8fixture", ""))
        self.assertEqual(
            get.call_args.args[0],
            "http://camera:8899/onvif/e01234567890123456789/snapshot.jpg?lens=2",
        )
        self.assertEqual(get.call_args.kwargs["auth"], ("bridge", "fixture"))
