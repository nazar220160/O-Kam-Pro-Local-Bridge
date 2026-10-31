import tempfile, threading, unittest
from unittest.mock import patch
from okam_bridge.archive import ArchiveManager
from okam_bridge.exports import ExportManager
from okam_bridge.accounts import AccountManager
from test_workspace import FakeClient, FakeBackend, FakeCamera
from test_exports import FakePublisher


class ArchiveManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = AccountManager(FakeClient, FakeBackend())
        self.exports = ExportManager(
            "ffmpeg", probe=lambda: True, publisher_factory=FakePublisher
        )
        self.manager.exports = self.exports
        self.key = self.manager.login("example", "valid-test")
        self.w = self.manager.get(self.key)
        self.cid = next(iter(self.w.records))
        self.w.records[self.cid].ip = "192.168.20.10"
        self.w.cameras[self.cid] = FakeCamera({"name": "Example"})
        self.archive = ArchiveManager(self.exports, self.tmp.name)

    def tearDown(self):
        self.exports.close()
        self.manager.close()
        self.archive.close()
        self.tmp.cleanup()

    def test_recording_is_off_until_explicitly_enabled(self):
        status = self.archive.status(self.w, self.cid)
        self.assertFalse(status["recording_enabled"])
        self.assertEqual(status["records"], [])
        with self.assertRaises(ValueError):
            self.archive.set_recording(self.w, self.cid, {"enabled": True})

    def test_sd_import_requires_server_listed_identifier(self):
        self.exports.configure(
            self.w,
            self.cid,
            {"enabled": True, "onvif": False, "advertise_host": "127.0.0.1"},
        )
        with self.assertRaises(ValueError):
            self.archive.import_sd(
                self.w, self.cid, {"source_id": "../../escape", "duration": 15}
            )

    def test_recording_file_cannot_be_read_through_other_account_or_path(self):
        with self.assertRaises(KeyError):
            self.archive.file(self.w, self.cid, "../../../manifest.sqlite3")

    def test_disabled_export_does_not_start_replay(self):
        with self.assertRaises(ValueError):
            self.archive.replay("unknown", "record")

    def test_invalid_recording_settings_do_not_stop_existing_recorder(self):
        status = self.exports.configure(
            self.w,
            self.cid,
            {"enabled": True, "onvif": False, "advertise_host": "127.0.0.1"},
        )

        class Worker:
            stopped = False

            def stop(self):
                self.stopped = True

            def join(self):
                pass

        worker = Worker()
        self.archive.recorders[status["export_id"]] = [worker]
        with self.assertRaises(ValueError):
            self.archive.set_recording(
                self.w, self.cid, {"enabled": True, "segment_seconds": 0}
            )
        self.assertFalse(worker.stopped)

    def test_disable_cannot_be_overtaken_by_pending_recorder_construction(self):
        status = self.exports.configure(
            self.w,
            self.cid,
            {"enabled": True, "onvif": False, "advertise_host": "127.0.0.1"},
        )
        entered = threading.Event()
        release = threading.Event()
        disabled = threading.Event()
        created = []

        class Worker:
            def __init__(self, *a, **k):
                entered.set()
                release.wait(2)
                self.running = False
                created.append(self)

            def start(self):
                self.running = True

            def stop(self):
                self.running = False

            def join(self):
                pass

            def status(self):
                return {"running": self.running}

        def enable():
            self.archive.set_recording(self.w, self.cid, {"enabled": True})

        def disable():
            self.archive.set_recording(self.w, self.cid, {"enabled": False})
            disabled.set()

        with patch("okam_bridge.archive.Recorder", Worker):
            start = threading.Thread(target=enable)
            start.start()
            self.assertTrue(entered.wait(1))
            stop = threading.Thread(target=disable)
            stop.start()
            time = __import__("time")
            time.sleep(0.05)
            release.set()
            start.join(3)
            stop.join(3)
        self.assertTrue(disabled.is_set())
        self.assertFalse(any(w.running for w in created))

    def test_recording_policy_persists_and_is_not_replaced_by_sd_defaults(self):
        store = self.archive.store
        store.set_policy(
            self.archive.owner(self.w),
            self.cid,
            retention_days=90,
            max_bytes=20 * 1024**3,
        )
        self.assertEqual(
            store.policy(self.archive.owner(self.w), self.cid),
            {"retention_days": 90, "max_bytes": 20 * 1024**3},
        )
