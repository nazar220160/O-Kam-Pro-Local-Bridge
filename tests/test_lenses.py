import struct
import unittest
from okam_bridge.transport import read_lens_frame
import test_bridge as fixtures


class BufferedSession:
    def __init__(self, data):
        self.data = bytearray(data)

    def read_exact(self, channel, size, timeout):
        out = bytes(self.data[:size])
        del self.data[:size]
        return out


class LensMetadataTests(unittest.TestCase):
    def test_reads_sensor_index_without_combining_streams(self):
        header = bytearray(32)
        header[:4] = bytes.fromhex("55aa15a8")
        header[4] = 1
        header[16:20] = (5).to_bytes(4, "little")
        header[26:28] = (2).to_bytes(2, "little")
        self.assertEqual(
            read_lens_frame(BufferedSession(header + b"video"), timeout=1),
            (b"video", 1, 2),
        )


class FakeLensCamera(fixtures.FakeCamera):
    def status(self):
        return {**super().status(), "lenses": [0, 1, 2]}

    def frames(self, kind, lens=0):
        yield b"\xff\xd8lens-" + str(lens).encode() + b"\xff\xd9"


class LensHTTPTests(fixtures.HTTPTests):
    def setUp(self):
        super().setUp()
        self.server.cameras = {"yard": FakeLensCamera()}

    def test_selects_requested_lens(self):
        status, _, data = self.request("/api/cameras/yard/snapshot.jpg?lens=2", True)
        self.assertEqual(status, 200)
        self.assertIn(b"lens-2", data)

    def test_catalog_reports_three_separate_lenses(self):
        _, _, body = self.request("/api/cameras", True)
        import json

        self.assertEqual(json.loads(body)[0]["lenses"], [0, 1, 2])

    def test_rejects_invalid_lens(self):
        self.assertEqual(
            self.request("/api/cameras/yard/snapshot.jpg?lens=-1", True)[0], 400
        )


class DiscoveryIsolationTests(unittest.TestCase):
    def test_requested_lens_is_not_reported_as_physical_sensor(self):
        from okam_bridge.camera import Camera

        camera = Camera({"id": "test"}, "ffmpeg")
        camera._media(15)
        self.assertEqual(camera.status()["lenses"], [0])
        camera.stop()
