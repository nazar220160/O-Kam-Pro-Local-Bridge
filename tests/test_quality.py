import unittest
from unittest.mock import patch
from urllib.parse import parse_qs
from okam_bridge.transport import set_video_quality
from okam_bridge.accounts import WorkspaceError
from test_workspace import FakeClient, FakeBackend, AccountManager


class QualityTests(unittest.TestCase):
    def test_official_quality_commands_use_param16_and_verified_values(self):
        for quality, value in [("high", "1"), ("medium", "2"), ("low", "4")]:
            sent = []
            with patch(
                "okam_bridge.transport.write_command",
                side_effect=lambda s, r: sent.append(r),
            ):
                set_video_quality(
                    object(),
                    {"username": "admin", "password": "native", "account_id": "123"},
                    quality,
                )
            q = parse_qs(sent[0][8:].decode().split("?", 1)[1])
            self.assertEqual(q["param"], ["16"])
            self.assertEqual(q["value"], [value])
            self.assertEqual(q["userId"], ["123"])

    def test_unknown_quality_is_not_sent(self):
        with self.assertRaises(ValueError):
            set_video_quality(object(), {"password": "native"}, "arbitrary")

    def test_selected_quality_reaches_camera_without_changing_substream(self):
        import time

        backend = FakeBackend()
        manager = AccountManager(FakeClient, backend)
        try:
            key = manager.login("first", "valid-test")
            w = manager.get(key)
            cid = w.catalog()[0]["id"]
            w.connect(cid, "192.168.20.10", 1, quality="low")
            for _ in range(100):
                if cid in w.cameras:
                    break
                time.sleep(0.01)
            self.assertEqual(w.cameras[cid].config["quality"], "low")
            self.assertEqual(w.catalog()[0]["quality"], "low")
            with self.assertRaises(WorkspaceError):
                w.connect(cid, None, 1, quality="unknown")
        finally:
            manager.close()


class QualityMetadataTests(unittest.TestCase):
    def test_old_resolution_probe_cannot_overwrite_new_stream_metadata(self):
        from okam_bridge.camera import Camera

        c = Camera({"id": "test"}, "ffmpeg")
        m = c._media(0)
        m.probe_version = 2
        with patch(
            "okam_bridge.camera.probe_h264",
            return_value={"width": 1920, "height": 1080},
        ):
            c._probe_source(0, b"old", 1)
        self.assertEqual(m.source, {})
        with patch(
            "okam_bridge.camera.probe_h264", return_value={"width": 448, "height": 256}
        ):
            c._probe_source(0, b"new", 2)
        self.assertEqual(m.source["width"], 448)

    def test_reconnect_reprobes_source_dimensions(self):
        from okam_bridge.camera import Camera

        c = Camera({"id": "test"}, "ffmpeg")
        m = c._media(0)
        m.probed = True
        m.probe_sps = b"old"
        m.source = {"width": 1920}
        c._clear_decoders()
        self.assertFalse(m.probed)
        self.assertEqual(m.source, {})
