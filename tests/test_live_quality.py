import threading
import unittest
from unittest.mock import Mock
from okam_bridge.accounts import AccountManager, WorkspaceError
from test_workspace import FakeClient, FakeBackend, FakeCamera


class LiveQualityTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.manager = AccountManager(FakeClient, self.backend)
        key = self.manager.login("first", "valid-test")
        self.w = self.manager.get(key)
        self.cid = next(iter(self.w.records))
        self.r = self.w.records[self.cid]
        self.camera = FakeCamera(
            {"id": self.cid, "name": "Fixture", "ip": "192.168.20.10", "substream": 1}
        )
        self.camera.lock = threading.RLock()
        self.camera.control = Mock(return_value={"state": "confirmed"})
        self.r.instance = self.camera
        self.r.phase = "ready"
        self.r.ip = "192.168.20.10"
        self.r.wanted = True
        self.w.cameras[self.cid] = self.camera

    def tearDown(self):
        self.manager.close()

    def test_quality_changes_on_same_native_connection_and_is_saved(self):
        generation = self.r.generation
        result = self.w.apply_stream(self.cid, "192.168.20.10", 1, "low")
        self.assertEqual(result["mode"], "live")
        self.camera.control.assert_called_once_with("quality", {"quality": "low"})
        self.assertIs(self.r.instance, self.camera)
        self.assertFalse(self.camera.stopped)
        self.assertEqual(self.r.generation, generation)
        self.assertEqual(self.r.phase, "ready")
        self.assertEqual(self.r.quality, "low")
        self.assertEqual(self.r.cached_config["quality"], "low")
        self.w.apply_stream(self.cid, None, 1, None)
        self.assertIsNone(self.r.quality)
        self.assertNotIn("quality", self.r.cached_config)
        self.assertEqual(self.camera.control.call_count, 1)

    def test_rejected_command_does_not_save_new_quality_or_reconnect(self):
        self.camera.control.return_value = {"state": "rejected", "result": -2}
        with self.assertRaises(WorkspaceError):
            self.w.apply_stream(self.cid, None, 1, "low")
        self.assertIsNone(self.r.quality)
        self.assertIs(self.r.instance, self.camera)
        self.assertFalse(self.camera.stopped)

    def test_ip_or_substream_changes_still_reconnect(self):
        from unittest.mock import patch

        with patch.object(self.w, "connect") as connect:
            self.assertEqual(
                self.w.apply_stream(self.cid, "192.168.20.11", 1, "low")["mode"],
                "reconnect",
            )
            connect.assert_called_once_with(self.cid, "192.168.20.11", 1, "low")
        self.camera.control.assert_not_called()

    def test_invalid_quality_never_reaches_camera(self):
        with self.assertRaises(WorkspaceError):
            self.w.apply_stream(self.cid, None, 1, "invalid")
        self.camera.control.assert_not_called()
