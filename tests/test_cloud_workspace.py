import threading
import time
import unittest
from unittest.mock import Mock, patch

from okam_bridge.accounts import AccountManager, LANBackend, WorkspaceError
from test_workspace import FakeBackend, FakeCamera, FakeClient


class CloudWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.manager = AccountManager(FakeClient, self.backend)
        self.workspace = self.manager.get(self.manager.login("first", "valid-test"))
        self.cid = next(iter(self.workspace.records))
        self.record = self.workspace.records[self.cid]

    def tearDown(self):
        self.manager.close()

    def wait_ready(self):
        for _ in range(100):
            if self.cid in self.workspace.cameras:
                return
            time.sleep(0.01)
        self.fail("Connection did not complete")

    def test_cloud_preparation_needs_no_lan_address_or_discovery(self):
        self.record.connection_mode = "cloud"
        self.record.account_metadata["lan_ip"] = "stale-account-field"
        backend = LANBackend("ffmpeg")
        with (
            patch("okam_bridge.accounts.resolve_client_id", return_value="A" * 15),
            patch("okam_bridge.accounts.get_service_parameter", return_value="service"),
            patch("okam_bridge.accounts.discover_lan") as discover,
        ):
            config = backend.prepare(self.record, "123456789", None, 1)
        discover.assert_not_called()
        self.assertNotIn("ip", config)
        self.assertEqual(config["connection_mode"], "cloud")
        self.assertEqual(config["account_id"], "123456789")

    def test_cloud_reconnect_preserves_lan_hint_and_reports_source(self):
        self.record.ip = "192.168.20.10"
        self.backend.prepare = Mock(return_value={"id": self.cid, "name": "Fixture"})
        self.workspace.connect(self.cid, connection_mode="cloud")
        self.wait_ready()
        camera = self.workspace.cameras[self.cid]
        self.assertEqual(camera.config["connection_mode"], "cloud")
        self.assertEqual(self.record.ip, "192.168.20.10")
        self.assertEqual(self.workspace.catalog()[0]["connection_mode"], "cloud")
        self.assertNotIn("native-secret", str(self.workspace.catalog()))

    def test_invalid_mode_cannot_replace_connection_or_saved_preferences(self):
        for mode in ("direct", None, {}, True):
            with self.assertRaises(WorkspaceError):
                self.workspace.connect(self.cid, connection_mode=mode)
        self.assertEqual(self.record.connection_mode, "lan")
        self.assertFalse(self.record.wanted)
        self.assertEqual(self.backend.created, [])

    def test_switch_back_to_lan_without_ip_uses_retained_manual_hint(self):
        self.record.ip = "192.168.20.10"
        self.record.connection_mode = "cloud"
        self.backend.prepare = lambda record, account_id, ip, substream: {
            "id": self.cid,
            "name": "Fixture",
            "ip": ip or record.ip,
        }
        self.workspace.connect(self.cid, connection_mode="lan")
        self.wait_ready()
        self.assertEqual(self.record.ip, "192.168.20.10")
        self.assertEqual(
            self.workspace.cameras[self.cid].config["connection_mode"], "lan"
        )

    def test_live_quality_retains_cloud_mode_and_explicit_route_change_reconnects(self):
        camera = FakeCamera(
            {"id": self.cid, "name": "Fixture", "connection_mode": "cloud"}
        )
        camera.lock = threading.RLock()
        camera.control = Mock(return_value={"state": "confirmed"})
        self.record.instance = camera
        self.record.phase = "ready"
        self.record.connection_mode = "cloud"
        self.workspace.cameras[self.cid] = camera
        self.assertEqual(
            self.workspace.apply_stream(self.cid, quality="low")["mode"], "live"
        )
        camera.control.assert_called_once_with("quality", {"quality": "low"})
        self.assertIs(self.record.instance, camera)
        with patch.object(self.workspace, "connect") as connect:
            result = self.workspace.apply_stream(
                self.cid, quality="low", connection_mode="lan"
            )
        self.assertEqual(result["mode"], "reconnect")
        connect.assert_called_once_with(self.cid, None, 1, "low", "lan")
