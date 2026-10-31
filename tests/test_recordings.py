import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from okam_bridge.recordings import RecordingStore, Recorder


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and ffprobe required")
class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = RecordingStore(self.root / "recordings", FFMPEG)
        self.sample = self.root / "sample.mkv"
        subprocess.run(
            [
                FFMPEG,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=size=64x64:rate=10",
                "-t",
                "1",
                "-c:v",
                "libx264",
                "-y",
                str(self.sample),
            ],
            check=True,
            timeout=10,
        )

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def add(
        self, name="one.mkv", owner="alice", camera="camera", source="server", start=100
    ):
        path = self.store.directory(owner, camera) / name
        shutil.copyfile(self.sample, path)
        return self.store.add_recording(
            owner, camera, path, source=source, lens=2, start=start, end=start + 1
        )

    def test_persistence_owner_isolation_and_public_metadata(self):
        first = self.add()
        self.assertNotIn("path", first)
        self.assertEqual(first["lens"], 2)
        self.assertEqual(len(self.store.list("alice", "camera")), 1)
        self.assertEqual(self.store.list("bob", "camera"), [])
        self.assertIsNone(self.store.get("bob", "camera", first["token"]))
        self.assertIsNone(self.store.get("alice", "other", first["token"]))
        self.assertEqual(
            Path(self.store.get("alice", "camera", first["token"])["path"]).name,
            "one.mkv",
        )
        self.store.close()
        self.store = RecordingStore(self.root / "recordings", FFMPEG)
        self.assertEqual(self.store.list("alice", "camera")[0]["token"], first["token"])

    def test_filters_and_sd_source(self):
        self.add(start=100)
        sd = self.add("sd.mkv", source="sd", start=200)
        self.assertEqual(self.store.list("alice", "camera", source="sd"), [sd])
        self.assertEqual(self.store.list("alice", "camera", start=150, end=250), [sd])
        self.assertEqual(self.store.list("alice", "camera", end=99), [])

    def test_path_escape_symlink_empty_and_invalid_video_rejected(self):
        directory = self.store.directory("alice", "camera")
        paths = [self.sample, self.store.directory("bob", "camera") / "foreign.mkv"]
        shutil.copyfile(self.sample, paths[1])
        link = directory / "link.mkv"
        link.symlink_to(self.sample)
        paths.append(link)
        empty = directory / "empty.mkv"
        empty.touch()
        paths.append(empty)
        invalid = directory / "invalid.mkv"
        invalid.write_bytes(b"not a video")
        paths.append(invalid)
        for path in paths:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.store.add_recording(
                    "alice", "camera", path, lens=0, start=1, end=2
                )
        self.assertEqual(self.store.list("alice", "camera"), [])

    def test_retention_and_quota_only_remove_owned_completed_records(self):
        old = self.add(start=100)
        current = self.add("new.mkv", start=time.time())
        foreign = self.add("other.mkv", owner="bob", start=100)
        foreign_path = self.store.get("bob", "camera", foreign["token"])["path"]
        partial = self.store.directory("alice", "camera") / "active.part.mkv"
        partial.write_bytes(b"active")
        self.store.enforce_limits("alice", "camera", retention_days=1, max_bytes=10**9)
        self.assertIsNone(self.store.get("alice", "camera", old["token"]))
        self.assertTrue(Path(foreign_path).exists())
        self.assertTrue(partial.exists())
        self.store.enforce_limits("alice", "camera", retention_days=1, max_bytes=0)
        self.assertEqual(self.store.list("alice", "camera"), [])
        self.assertTrue(partial.exists())

    def test_symlink_swap_is_never_followed_on_get_or_prune(self):
        recording = self.add()
        path = Path(self.store.get("alice", "camera", recording["token"])["path"])
        path.unlink()
        path.symlink_to(self.sample)
        self.assertIsNone(self.store.get("alice", "camera", recording["token"]))
        self.store.enforce_limits("alice", "camera", retention_days=0, max_bytes=0)
        self.assertTrue(self.sample.exists())

    def test_invalid_options_and_no_auto_start(self):
        recorder = Recorder(None, 0, self.store, "alice", "camera", segment_seconds=5)
        self.assertFalse(recorder.status()["running"])
        with self.assertRaises(ValueError):
            Recorder(None, 0, self.store, "alice", "camera", segment_seconds=4)

    def test_incomplete_filename_and_invalid_metadata_never_indexed(self):
        path = self.store.directory("alice", "camera") / "active.part.mkv"
        shutil.copyfile(self.sample, path)
        with self.assertRaises(ValueError):
            self.store.add_recording("alice", "camera", path, start=1, end=2)
        final = path.with_name("finished.mkv")
        path.rename(final)
        for kwargs in [
            {"source": "invalid"},
            {"lens": -1},
            {"start": float("nan")},
            {"end": 0},
            {"start": "2026-01-01T00:00:00"},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.store.add_recording(
                    "alice", "camera", final, **({"start": 1, "end": 2} | kwargs)
                )
        self.assertEqual(self.store.list("alice", "camera"), [])

    def test_real_h264_worker_commits_probeable_recording_and_stops(self):
        raw = subprocess.run(
            [
                FFMPEG,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=size=64x64:rate=10",
                "-t",
                "1",
                "-c:v",
                "libx264",
                "-f",
                "h264",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
            timeout=10,
        ).stdout

        class Camera:
            def status(self):
                return {"lens_metadata": [{"id": 2, "reported_fps": 10}]}

            def frames(self, kind, lens=0, cancel=None):
                self.kind, self.lens = kind, lens
                yield raw

        camera = Camera()
        recorder = Recorder(camera, 2, self.store, "alice", "camera", segment_seconds=5)
        recorder.start()
        deadline = time.monotonic() + 8
        while not self.store.list("alice", "camera") and time.monotonic() < deadline:
            time.sleep(0.05)
        recorder.stop()
        recorder.join()
        self.assertFalse(recorder.status()["running"])
        self.assertEqual((camera.kind, camera.lens), ("h264", 2))
        recordings = self.store.list("alice", "camera")
        self.assertTrue(recordings, recorder.status())
        self.assertGreater(recordings[0]["duration"], 0)
        self.assertGreater(recorder.status()["bytes"], 0)
        recorded_path = self.store.get("alice", "camera", recordings[0]["token"])[
            "path"
        ]
        decoded = subprocess.run(
            [
                FFMPEG,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                recorded_path,
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(decoded.returncode, 0, decoded.stderr.decode())

    def test_stalled_feed_cancelled_promptly_and_no_partial_listing(self):
        entered = threading.Event()

        class Camera:
            def status(self):
                return {}

            def frames(self, kind, lens=0, cancel=None):
                entered.set()
                cancel.wait(10)
                return
                yield b""

        recorder = Recorder(
            Camera(), 0, self.store, "alice", "camera", segment_seconds=5
        )
        recorder.start()
        self.assertTrue(entered.wait(2))
        started = time.monotonic()
        recorder.stop()
        recorder.join()
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(recorder.status()["running"])
        self.assertEqual(self.store.list("alice", "camera"), [])


if __name__ == "__main__":
    unittest.main()
