import shutil
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from okam_bridge.sd_archive import (
    MAGIC,
    MAX_FRAME_BYTES,
    SDArchive,
    SDSession,
    iter_frames,
    parse_dates,
    parse_frame_header,
    parse_index,
)
from okam_bridge.vendor.cs2 import CS2Timeout


def index_data(stamp=1700000000):
    return (
        struct.pack("<BIHB", 8, stamp, 2, 2)
        + struct.pack("<BIHB", 1, stamp, 0, 30)
        + struct.pack("<BIHB", 1, stamp + 2, 30, 30)
        + struct.pack("<BIHB", 2, stamp + 5, 75, 0)
    )


def frame(payload=b"", typ=99, lens=0, fps=10, sequence=0):
    header = bytearray(32)
    header[:4] = MAGIC
    header[4] = typ
    struct.pack_into("<II", header, 12, sequence, len(payload))
    struct.pack_into("<HH", header, 26, lens, fps)
    return bytes(header) + payload


class FakeSession:
    data = b""
    calls = []

    def __init__(self, config):
        self.buffer = bytearray(self.data)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def request(self, path, command, **kwargs):
        self.calls.append(path)
        return b"result=0;"

    def send(self, path):
        self.calls.append(path)

    def read(self, count, deadline, cancel):
        if len(self.buffer) < count:
            raise CS2Timeout("end of fixture")
        result = bytes(self.buffer[:count])
        del self.buffer[:count]
        return result


class SDArchiveTests(unittest.TestCase):
    def setUp(self):
        FakeSession.calls = []
        FakeSession.data = b""
        self.archive = SDArchive({})
        self.record = parse_index(index_data())[0]

    def test_index_and_utc_event_filename(self):
        record = self.record
        self.assertEqual(record["event"], 2)
        self.assertTrue(record["filename"].endswith("_011.mp4"))
        self.assertEqual(record["duration"], 5)
        self.assertTrue(record["start"].endswith("Z"))
        self.assertEqual(record["id"], parse_index(index_data())[0]["id"])
        self.assertEqual(record["keyframes"][1]["frame_no"], 30)
        self.assertNotEqual(record["id"], parse_index(index_data(1700000001))[0]["id"])

    def test_invalid_index_rejected(self):
        for value in (
            index_data()[:-1],
            index_data()[:8],
            b"\1" + index_data()[1:],
            index_data()[:8] + b"\0" + index_data()[9:],
        ):
            with self.subTest(value=len(value)), self.assertRaises(ValueError):
                parse_index(value)
        self.assertEqual(parse_index(b""), [])

    def test_dates_known_legacy_array_only(self):
        self.assertEqual(
            parse_dates(
                b'var record_datenum=4;record_date[0]="20261031";record_date[1]=20260230;record_date[2]="20261031";other[0]="20260101";'
            ),
            ["20261031"],
        )
        with self.assertRaises(ValueError):
            self.archive.list_records("../20261031")

    def test_control_frames_and_incomplete_last(self):
        data = (
            frame()
            + frame(b"\0\0\0\1\x67abc", typ=0, lens=2)
            + frame(b"partial", typ=1)[:-3]
        )
        parsed = list(iter_frames(data, allow_incomplete=True))
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0][0]["type"], 99)
        self.assertEqual(parsed[1][0]["lens"], 2)
        with self.assertRaises(ValueError):
            list(iter_frames(data))
        with self.assertRaises(ValueError):
            list(iter_frames(b"short"))

    def test_frame_bounds_and_magic(self):
        for offset, value, fmt in ((16, MAX_FRAME_BYTES + 1, "<I"), (26, 16, "<H")):
            header = bytearray(frame())
            struct.pack_into(fmt, header, offset, value)
            with self.assertRaises(ValueError):
                parse_frame_header(header)
        with self.assertRaises(ValueError):
            parse_frame_header(b"X" * 32)

    def test_cancel_stops_native_session(self):
        event = threading.Event()
        event.set()
        with tempfile.TemporaryDirectory() as directory, patch(
            "okam_bridge.sd_archive.SDSession", FakeSession
        ):
            with self.assertRaises(InterruptedError):
                self.archive.fetch(self.record, directory, cancel=event)
            self.assertEqual(FakeSession.calls, ["livestream.cgi?streamid=17&"])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_malformed_frame_stops_and_cleans(self):
        FakeSession.data = b"X" * 32
        with tempfile.TemporaryDirectory() as directory, patch(
            "okam_bridge.sd_archive.SDSession", FakeSession
        ):
            with self.assertRaises(ValueError):
                self.archive.fetch(self.record, directory)
            self.assertIn("streamid=5", FakeSession.calls[0])
            self.assertEqual(FakeSession.calls[-1], "livestream.cgi?streamid=17&")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_read_retries_same_boundary(self):
        class Native:
            def __init__(self):
                self.calls = []

            def read_exact(self, channel, count, timeout):
                self.calls.append((channel, count))
                if len(self.calls) == 1:
                    raise CS2Timeout("partial")
                return b"test"

        session = SDSession({})
        session.session = Native()
        self.assertEqual(session.read(4, time.monotonic() + 2, None), b"test")
        self.assertEqual(session.session.calls, [(4, 4), (4, 4)])

    def test_index_prefix(self):
        class Listing(FakeSession):
            def request(self, path, command, **kwargs):
                return b"result=0;\0\0\0" + index_data()

        with patch("okam_bridge.sd_archive.SDSession", Listing):
            self.assertEqual(self.archive.list_records("20261031"), [self.record])

    def test_index_pagination_limit(self):
        class Listing(FakeSession):
            def request(self, path, command, **kwargs):
                self.calls.append(path)
                return b"result=0;\0\0\0" + b"\0" * 60000

        with patch("okam_bridge.sd_archive.SDSession", Listing):
            with self.assertRaisesRegex(ValueError, "page limit"):
                self.archive.list_records("20261031")
        self.assertEqual(len(FakeSession.calls), 128)

    def test_duration_limits_before_network(self):
        for duration in (0, -1, 301, float("nan"), True):
            with tempfile.TemporaryDirectory() as directory, patch(
                "okam_bridge.sd_archive.SDSession", FakeSession
            ):
                with self.assertRaises(ValueError):
                    self.archive.fetch(self.record, directory, max_seconds=duration)
        self.assertEqual(FakeSession.calls, [])

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required"
    )
    def test_three_lens_remux_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            sample = Path(directory) / "sample.h264"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=size=64x64:rate=10",
                    "-frames:v",
                    "1",
                    "-c:v",
                    "libx264",
                    "-f",
                    "h264",
                    str(sample),
                ],
                check=True,
                timeout=10,
            )
            payload = sample.read_bytes()
            sample.unlink()
            FakeSession.data = (
                frame()
                + b"".join(frame(payload, typ=0, lens=lens) for lens in (1, 2, 0))
                + frame(payload, typ=1, sequence=1)
            )
            with patch("okam_bridge.sd_archive.SDSession", FakeSession):
                results = self.archive.fetch(self.record, directory, max_seconds=0.1)
            self.assertEqual({r["lens"] for r in results}, {0, 1, 2})
            self.assertEqual(len(list(Path(directory).glob("*.mkv"))), 3)
            self.assertEqual(len(list(Path(directory).glob("*.h264"))), 0)
            self.assertTrue(all(r["source"] == "sd" for r in results))
            self.assertEqual(FakeSession.calls[-1], "livestream.cgi?streamid=17&")


if __name__ == "__main__":
    unittest.main()
