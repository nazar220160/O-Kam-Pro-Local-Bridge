import json, time, unittest
from unittest.mock import patch
from okam_bridge.exports import ExportManager, ExportError, publisher_command
from okam_bridge.accounts import AccountManager
from test_workspace import FakeClient, FakeBackend, FakeCamera


class FakePublisher:
    def __init__(self, camera, lens, *args):
        self.camera = camera
        self.lens = lens
        self.stopped = False
        self.written = 1
        self.error = None

    def start(self):
        pass

    def stop(self):
        self.stopped = True

    def join(self):
        pass


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.manager = AccountManager(FakeClient, FakeBackend(), ttl=0.01)
        self.registry = ExportManager(
            "ffmpeg", probe=lambda: True, publisher_factory=FakePublisher
        )
        self.manager.exports = self.registry
        self.key = self.manager.login("example", "valid-test")
        self.w = self.manager.get(self.key)
        self.cid = next(iter(self.w.records))
        self.w.records[self.cid].ip = "192.168.20.10"
        self.camera = FakeCamera({"name": "Example"})
        self.w.cameras[self.cid] = self.camera

    def tearDown(self):
        self.registry.close()
        self.manager.close()

    def enable(self, **extra):
        return self.registry.configure(
            self.w,
            self.cid,
            {
                "enabled": True,
                "advertise_host": "192.168.20.1",
                "rtsp": True,
                "onvif": False,
                **extra,
            },
        )

    def test_publication_has_profiles_but_credentials_are_explicit_and_scoped(self):
        status = self.enable()
        self.assertTrue(status["enabled"])
        self.assertEqual(len(status["profiles"]), 3)
        credentials = self.registry.credentials(self.w, self.cid)
        self.assertNotIn(credentials["password"], json.dumps(status))
        self.assertNotIn("native-secret", json.dumps(status))
        uri = status["profiles"][0]["rtsp_uri"]
        self.assertNotIn("@", uri)
        path = uri.split(":8554/", 1)[1]
        self.assertTrue(
            self.registry.authenticate(
                {
                    "action": "read",
                    "protocol": "rtsp",
                    "path": path,
                    **{
                        "user": credentials["username"],
                        "password": credentials["password"],
                    },
                }
            )
        )
        self.assertFalse(
            self.registry.authenticate(
                {
                    "action": "publish",
                    "protocol": "rtsp",
                    "path": path,
                    "user": credentials["username"],
                    "password": credentials["password"],
                }
            )
        )
        self.assertFalse(
            self.registry.authenticate(
                {
                    "action": "read",
                    "protocol": "rtsp",
                    "path": path + "extra",
                    "user": credentials["username"],
                    "password": credentials["password"],
                }
            )
        )

    def test_logout_and_disconnect_revoke_export_and_prevent_stale_auth(self):
        self.enable()
        self.assertTrue(self.registry.status(self.w, self.cid)["enabled"])
        self.w.disconnect(self.cid)
        self.assertFalse(self.registry.status(self.w, self.cid)["enabled"])
        self.w.cameras[self.cid] = self.camera
        self.enable()
        self.manager.logout(self.key)
        self.assertFalse(self.registry.has_workspace(self.w))

    def test_active_export_keeps_owning_session_until_disabled(self):
        self.enable()
        time.sleep(0.02)
        self.manager.prune()
        self.assertIs(self.manager.get(self.key), self.w)
        self.registry.configure(self.w, self.cid, {"enabled": False})
        self.manager.prune()
        self.assertIsNone(self.manager.get(self.key))

    def test_enabled_requires_connected_camera_and_safe_advertise_host(self):
        for host in ["http://evil/x", "name@host", "host:123", "a\ninvalid"]:
            with self.assertRaises(ExportError):
                self.enable(advertise_host=host)
        self.w.cameras.clear()
        with self.assertRaises(ExportError):
            self.enable()

    def test_publisher_copies_original_h264_and_uses_only_rtsp_tcp(self):
        command = publisher_command("ffmpeg", "rtsp://127.0.0.1:8554/path", 10)
        self.assertEqual(command[command.index("-c:v") + 1], "copy")
        self.assertEqual(command[command.index("-rtsp_transport") + 1], "tcp")
        self.assertIn("pipe:0", command)
        self.assertNotIn("libx264", command)

    def test_another_workspace_cannot_access_or_disable_export(self):
        self.enable()
        other = self.manager.login("second", "valid-test")
        w = self.manager.get(other)
        self.assertFalse(self.registry.status(w, self.cid)["enabled"])
        self.registry.configure(w, self.cid, {"enabled": False})
        self.assertTrue(self.registry.status(self.w, self.cid)["enabled"])


class ExportLifecycleRaceTests(unittest.TestCase):
    def test_disable_supersedes_enable_waiting_for_service_setup(self):
        import threading

        manager = AccountManager(FakeClient, FakeBackend())
        registry = ExportManager("ffmpeg", publisher_factory=FakePublisher)
        manager.exports = registry
        key = manager.login("example", "valid-test")
        w = manager.get(key)
        cid = next(iter(w.records))
        w.records[cid].ip = "192.168.20.10"
        w.cameras[cid] = FakeCamera({"name": "Example"})
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def probe():
            entered.set()
            release.wait(2)
            return True

        registry.probe = probe

        def enable():
            try:
                registry.configure(
                    w,
                    cid,
                    {"enabled": True, "advertise_host": "192.168.20.1", "onvif": False},
                )
            except ExportError as e:
                errors.append(str(e))

        thread = threading.Thread(target=enable)
        thread.start()
        self.assertTrue(entered.wait(1))
        registry.configure(w, cid, {"enabled": False})
        release.set()
        thread.join(3)
        self.assertFalse(registry.has_workspace(w))
        self.assertIn("export_superseded", errors)
        registry.close()
        manager.close()

    def test_publisher_cancellation_releases_camera_subscription_without_frames(self):
        import threading
        from okam_bridge.camera import Camera

        camera = Camera({"id": "fixture", "name": "Fixture"}, "ffmpeg")
        cancel = threading.Event()
        camera._run = lambda: camera.stop_event.wait(1)
        result = []

        def consume():
            try:
                list(camera.frames("h264", cancel=cancel))
                result.append("closed")
            except Exception as e:
                result.append(type(e).__name__)

        thread = threading.Thread(target=consume)
        thread.start()
        time.sleep(0.03)
        cancel.set()
        thread.join(0.7)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, ["closed"])
        self.assertEqual(camera.status()["viewers"], 0)
        camera.stop()
