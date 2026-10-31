import threading
import time
import unittest
from okam_bridge.vendor.account import AccountDevice, AccountError
from okam_bridge.accounts import AccountManager, public_account_metadata


class FakeClient:
    def __init__(self):
        self.user_id = "123456789"
        self.raw_items = []

    def enumerate(self, username, password):
        if password != "valid-test":
            raise AccountError("Rejected")
        self.raw_items = [
            {
                "uid": "ABCD123456ABCDE",
                "nickname": username + " camera",
                "password": "native-secret",
                "security": "secret",
                "model": "Three lens",
                "online": 1,
            }
        ]
        return [
            AccountDevice(
                uid="ABCD123456ABCDE",
                name=username + " camera",
                device_password="native-secret",
            )
        ]

    def refresh_devices(self):
        return self.enumerate("refreshed", "valid-test")


class FakeCamera:
    def __init__(self, c):
        self.name = c["name"]
        self.config = c
        self.stopped = False

    def frames(self, kind, lens=0):
        yield b"\xff\xd8test\xff\xd9"

    def status(self):
        return {
            "state": "streaming",
            "lenses": [0, 1, 2],
            "metadata": {},
            "lens_metadata": [],
        }

    def stop(self):
        self.stopped = True


class FakeBackend:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.created = []

    def prepare(self, record, account_id, ip, substream):
        self.entered.set()
        if self.block:
            self.release.wait(2)
        return {
            "id": record.id,
            "name": record.device.name,
            "account_id": account_id,
            "ip": ip or "192.168.20.11",
        }

    def camera(self, config):
        c = FakeCamera(config)
        self.created.append(c)
        return c


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.manager = AccountManager(FakeClient, self.backend)

    def tearDown(self):
        self.backend.release.set()
        self.manager.close()

    def test_any_account_catalog_is_isolated_and_redacted(self):
        a = self.manager.login("first", "valid-test")
        b = self.manager.login("second", "valid-test")
        self.assertNotEqual(a, b)
        wa = self.manager.get(a)
        wb = self.manager.get(b)
        self.assertEqual(wa.catalog()[0]["name"], "first camera")
        self.assertEqual(wb.catalog()[0]["name"], "second camera")
        self.assertNotIn("native-secret", str(wa.catalog()))
        self.assertNotIn("security", str(wa.catalog()))
        self.assertFalse(hasattr(wa, "password"))

    def test_failed_login_does_not_create_session(self):
        with self.assertRaises(AccountError):
            self.manager.login("any", "wrong")
        self.assertEqual(len(self.manager.workspaces), 0)

    def test_logout_cannot_resurrect_pending_camera(self):
        key = self.manager.login("first", "valid-test")
        w = self.manager.get(key)
        self.backend.block = True
        cid = w.catalog()[0]["id"]
        w.connect(cid, None, 1)
        self.assertTrue(self.backend.entered.wait(1))
        self.manager.logout(key)
        self.backend.release.set()
        time.sleep(0.05)
        self.assertIsNone(self.manager.get(key))
        self.assertEqual(w.cameras, {})
        self.assertTrue(all(c.stopped for c in self.backend.created))

    def test_connect_uses_this_account_and_disconnect_stops(self):
        key = self.manager.login("shared", "valid-test")
        w = self.manager.get(key)
        cid = w.catalog()[0]["id"]
        w.connect(cid, "192.168.20.11", 1)
        for _ in range(100):
            if cid in w.cameras:
                break
            time.sleep(0.01)
        self.assertEqual(w.cameras[cid].config["account_id"], "123456789")
        camera = w.cameras[cid]
        w.disconnect(cid)
        self.assertTrue(camera.stopped)

    def test_refresh_updates_list_without_carrying_password_to_output(self):
        key = self.manager.login("first", "valid-test")
        w = self.manager.get(key)
        w.refresh()
        self.assertEqual(w.catalog()[0]["name"], "refreshed camera")

    def test_public_metadata_uses_allowlist(self):
        m = public_account_metadata(
            {
                "model": "Example",
                "online": 1,
                "password": "secret",
                "security": "secret",
                "token": "secret",
                "owner_email": "private",
            }
        )
        self.assertEqual(m, {"model": "Example", "account_online": True})


class ExpiryTests(unittest.TestCase):
    def test_expired_workspace_is_closed_without_next_account_access(self):
        manager = AccountManager(FakeClient, FakeBackend(), ttl=1)
        key = manager.login("any", "valid-test")
        workspace = manager.get(key)
        workspace.created -= 2
        manager.prune()
        self.assertTrue(workspace.closed)
        self.assertIsNone(manager.get(key))
        manager.close()


class ConcurrencyTests(unittest.TestCase):
    def test_connect_reserves_job_before_stopping_previous_session(self):
        from okam_bridge.accounts import WorkspaceError

        backend = FakeBackend()
        manager = AccountManager(FakeClient, backend)
        key = manager.login("first", "valid-test")
        w = manager.get(key)
        cid = w.catalog()[0]["id"]
        w.connect(cid, None, 1)
        for _ in range(100):
            if cid in w.cameras:
                break
            time.sleep(0.01)
        entered = threading.Event()
        release = threading.Event()
        old = w.cameras[cid]

        def stop():
            entered.set()
            release.wait(2)
            old.stopped = True

        old.stop = stop
        t = threading.Thread(target=w.connect, args=(cid, None, 1))
        t.start()
        try:
            self.assertTrue(entered.wait(1))
            with self.assertRaises(WorkspaceError):
                w.connect(cid, None, 1)
        finally:
            release.set()
            t.join()
            manager.close()


class AddressTests(unittest.TestCase):
    def test_account_private_ip_is_reported_but_public_ip_is_ignored(self):
        self.assertEqual(
            public_account_metadata({"ip": "192.168.20.11"}),
            {"lan_ip": "192.168.20.11"},
        )
        self.assertEqual(public_account_metadata({"ip": "8.8.8.8"}), {})

    def test_known_account_ip_does_not_trigger_lan_discovery(self):
        from unittest.mock import patch
        from okam_bridge.accounts import LANBackend, Record

        r = Record(
            "any",
            AccountDevice(uid="original", name="Any", device_password="native"),
            account_metadata={"lan_ip": "192.168.20.11"},
        )
        with patch(
            "okam_bridge.accounts.resolve_client_id", return_value="ABCD123456ABCDE"
        ), patch(
            "okam_bridge.accounts.get_service_parameter", return_value="parameter"
        ), patch(
            "okam_bridge.accounts.discover_lan",
            side_effect=AssertionError("Unnecessary discovery"),
        ):
            c = LANBackend("ffmpeg").prepare(r, "123", None, 1)
        self.assertEqual(c["ip"], "192.168.20.11")


class CatalogLifecycleTests(unittest.TestCase):
    def test_refresh_response_cannot_restore_secrets_after_logout(self):
        from unittest.mock import patch
        from okam_bridge.accounts import CatalogClient
        from okam_bridge.vendor.account import Eye4AccountClient

        client = CatalogClient()
        client.user_id = "123"
        client._device_digest = "digest"
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def response(*args, **kwargs):
            entered.set()
            release.wait(2)
            return [{"uid": "ABCD123456ABCDE", "password": "native-secret"}]

        def refresh():
            try:
                client.refresh_devices()
            except AccountError:
                errors.append(True)

        with patch.object(Eye4AccountClient, "_request_json", response):
            t = threading.Thread(target=refresh)
            t.start()
            self.assertTrue(entered.wait(1))
            client.clear()
            release.set()
            t.join()
        self.assertEqual(client.raw_items, [])
        self.assertIsNone(client._device_digest)
        self.assertTrue(errors)


class EncryptedAccountTests(unittest.TestCase):
    def test_backend_decodes_only_selected_record_and_keeps_token_out_of_catalog(self):
        from unittest.mock import patch
        from okam_bridge.accounts import LANBackend, Record

        backend = LANBackend("ffmpeg")
        r = Record(
            "one",
            AccountDevice(
                uid="original", name="Any", device_password="", security="a" * 32
            ),
            check_value="789",
            account_token="private-token",
        )
        with patch(
            "okam_bridge.accounts.resolve_client_id", return_value="ABCD123456ABCDE"
        ), patch(
            "okam_bridge.accounts.get_service_parameter", return_value="parameter"
        ), patch.object(
            backend.decoder, "decode", return_value="decoded-secret"
        ) as decoder:
            config = backend.prepare(r, "123", "192.168.20.10", 1)
        decoder.assert_called_once_with("a" * 32, "789")
        self.assertEqual(config["password"], "decoded-secret")
        self.assertEqual(config["account_id"], "123")
        self.assertEqual(config["account_token"], "private-token")
