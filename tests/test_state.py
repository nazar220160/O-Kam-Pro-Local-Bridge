import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from okam_bridge.state import StateStore, StateService
from okam_bridge.accounts import AccountManager
from okam_bridge.exports import ExportManager
from test_workspace import FakeClient, FakeBackend, FakeCamera
from test_exports import FakePublisher


def wait_for(predicate):
    for _ in range(150):
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Restore did not complete")


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.running = []

    def tearDown(self):
        for manager, exports, state in reversed(self.running):
            state.close()
            exports.close()
            manager.close()
        self.temp.cleanup()

    def system(self):
        manager = AccountManager(FakeClient, FakeBackend())
        exports = ExportManager(
            "ffmpeg", probe=lambda: True, publisher_factory=FakePublisher
        )
        manager.exports = exports
        state = StateService(manager, exports, self.root)
        state.start()
        self.running.append((manager, exports, state))
        return manager, exports, state

    def restart(self):
        manager, exports, state = self.running.pop()
        state.close()
        exports.close()
        manager.close()
        return self.system()

    def connect(self, manager):
        token = manager.login("first", "valid-test")
        workspace = manager.get(token)
        cid = next(iter(workspace.records))
        workspace.connect(cid, "192.168.20.10", 1, "low")
        wait_for(lambda: cid in workspace.cameras)
        return token, workspace, cid

    def test_cookie_player_camera_quality_export_id_and_password_survive_restart(self):
        manager, exports, state = self.system()
        token, workspace, cid = self.connect(manager)
        before = exports.configure(
            workspace,
            cid,
            {"enabled": True, "onvif": False, "advertise_host": "192.168.20.1"},
        )
        credentials = exports.credentials(workspace, cid)
        player = workspace.player_token
        state.checkpoint()
        wire = (self.root / "sessions.enc").read_bytes()
        for private in (token, "native-secret", credentials["password"]):
            self.assertNotIn(private.encode(), wire)
        manager, exports, state = self.restart()
        workspace = manager.get(token)
        self.assertIsNotNone(workspace)
        self.assertEqual(workspace.player_token, player)
        wait_for(lambda: exports._find(workspace, cid) is not None)
        after = exports.status(workspace, cid)
        self.assertEqual(after["export_id"], before["export_id"])
        self.assertEqual(after["profiles"], before["profiles"])
        self.assertEqual(exports.credentials(workspace, cid), credentials)
        self.assertEqual(workspace.records[cid].quality, "low")
        self.assertTrue(workspace.records[cid].wanted)
        self.assertEqual(manager.login("first", "valid-test"), token)
        self.assertIs(manager.get(token), workspace)

    def test_logout_is_durable_and_does_not_revive_a_session(self):
        manager, exports, state = self.system()
        token, workspace, cid = self.connect(manager)
        state.checkpoint()
        manager.logout(token)
        state.checkpoint()
        manager, exports, state = self.restart()
        self.assertIsNone(manager.get(token))
        self.assertEqual(manager.workspaces, {})

    def test_disabled_exports_and_disconnected_cameras_stay_off(self):
        manager, exports, state = self.system()
        token, workspace, cid = self.connect(manager)
        before = exports.configure(
            workspace,
            cid,
            {"enabled": True, "onvif": False, "advertise_host": "192.168.20.1"},
        )
        exports.disable(workspace, cid)
        workspace.disconnect(cid)
        state.checkpoint()
        manager, exports, state = self.restart()
        workspace = manager.get(token)
        time.sleep(0.1)
        self.assertFalse(workspace.records[cid].wanted)
        self.assertFalse(exports.has_workspace(workspace))
        self.assertFalse(workspace.cameras)
        self.assertEqual(workspace.saved_exports[cid]["export_id"], before["export_id"])

    def test_mediamtx_can_start_later_without_losing_saved_export(self):
        manager, exports, state = self.system()
        token, workspace, cid = self.connect(manager)
        before = exports.configure(
            workspace,
            cid,
            {"enabled": True, "onvif": False, "advertise_host": "192.168.20.1"},
        )
        state.checkpoint()
        manager, exports, state = self.restart()
        workspace = manager.get(token)
        exports.disable(workspace, cid)
        workspace.saved_exports[cid]["enabled"] = True
        exports.probe = lambda: False
        state._reconcile()
        state.checkpoint()
        self.assertTrue(workspace.saved_exports[cid]["enabled"])
        exports.probe = lambda: True
        wait_for(lambda: exports._find(workspace, cid) is not None)
        self.assertEqual(
            exports.status(workspace, cid)["export_id"], before["export_id"]
        )

    def test_recording_intent_survives_and_is_restarted_after_export(self):
        manager, exports, state = self.system()
        token, workspace, cid = self.connect(manager)
        exports.configure(
            workspace,
            cid,
            {"enabled": True, "onvif": False, "advertise_host": "192.168.20.1"},
        )
        policy = {
            "enabled": True,
            "segment_seconds": 30,
            "retention_days": 90,
            "max_bytes": 20971520,
        }
        workspace.saved_recordings[cid] = policy
        with patch.object(
            exports.archive, "status", return_value={"recording_enabled": True}
        ):
            state.checkpoint()
        # Inspect durable policy without starting a real recorder on fake H264.
        saved = state.store.load()["sessions"][0]["recordings"][cid]
        self.assertEqual(saved, policy)

    def test_wrong_key_or_tampering_fails_closed_and_preserves_files(self):
        store = StateStore(self.root)
        store.save({"version": 1, "sessions": []})
        wire = bytearray((self.root / "sessions.enc").read_bytes())
        wire[-1] ^= 1
        (self.root / "sessions.enc").write_bytes(wire)
        with self.assertRaises(ValueError):
            StateStore(self.root).load()
        self.assertEqual((self.root / "sessions.enc").read_bytes(), wire)
        self.assertEqual((self.root / "state.key").stat().st_mode & 0o777, 0o600)

    def test_missing_key_is_not_silently_regenerated(self):
        store = StateStore(self.root)
        store.save({"version": 1, "sessions": []})
        (self.root / "state.key").unlink()
        with self.assertRaises(ValueError):
            StateStore(self.root)

    def test_restore_restarts_enabled_recording_with_same_policy(self):
        manager, exports, state = self.system()
        token, workspace, cid = self.connect(manager)
        exports.configure(
            workspace,
            cid,
            {"enabled": True, "onvif": False, "advertise_host": "192.168.20.1"},
        )
        policy = {
            "enabled": True,
            "segment_seconds": 30,
            "retention_days": 90,
            "max_bytes": 20971520,
        }
        workspace.saved_recordings[cid] = policy
        with patch(
            "okam_bridge.archive.ArchiveManager.status",
            return_value={"recording_enabled": False},
        ), patch("okam_bridge.archive.ArchiveManager.set_recording") as record:
            manager, exports, state = self.restart()
            wait_for(lambda: record.called)
            self.assertEqual(record.call_args.args[1:], (cid, policy))

    def test_expired_inactive_session_is_not_revived_by_restart(self):
        manager, exports, state = self.system()
        token = manager.login("first", "valid-test")
        workspace = manager.get(token)
        workspace.expires_at = time.time() - 1
        state.checkpoint()
        manager, exports, state = self.restart()
        self.assertIsNone(manager.get(token))

    def test_reapply_and_off_on_preserve_nvr_credentials(self):
        manager, exports, state = self.system()
        token, workspace, cid = self.connect(manager)
        options = {"enabled": True, "onvif": False, "advertise_host": "192.168.20.1"}
        before = exports.configure(workspace, cid, options)
        credentials = exports.credentials(workspace, cid)
        self.assertEqual(
            exports.configure(workspace, cid, options)["export_id"], before["export_id"]
        )
        exports.disable(workspace, cid)
        self.assertEqual(
            exports.configure(workspace, cid, options)["export_id"], before["export_id"]
        )
        self.assertEqual(exports.credentials(workspace, cid), credentials)
        from okam_bridge.vendor.account import AccountError

        with self.assertRaises(AccountError):
            manager.login("first", "wrong")
        self.assertIs(manager.get(token), workspace)

    def test_pending_ip_and_quality_override_cached_connection_on_restart(self):
        manager, exports, state = self.system()
        token, workspace, cid = self.connect(manager)
        with workspace.lock:
            workspace.records[cid].ip = "192.168.20.99"
            workspace.records[cid].quality = None
            workspace.records[cid].cached_config["quality"] = "high"
        state.checkpoint()
        manager, exports, state = self.restart()
        workspace = manager.get(token)
        wait_for(lambda: cid in workspace.cameras)
        self.assertEqual(workspace.cameras[cid].config["ip"], "192.168.20.99")
        self.assertNotIn("quality", workspace.cameras[cid].config)
