import unittest
from okam_bridge.metadata import camera_status_metadata, frame_fps


class MetadataTests(unittest.TestCase):
    def test_status_projection_never_leaks_authentication_fields(self):
        raw = b'result=0;var sys_ver="10.0.1";var haveMic=1;var password="secret";var userId=123;var deviceid="private";'
        self.assertEqual(
            camera_status_metadata(raw), {"firmware": "10.0.1", "microphone": True}
        )

    def test_reported_frame_rate_is_validated(self):
        h = bytearray(32)
        h[28:30] = (10).to_bytes(2, "little")
        self.assertEqual(frame_fps(h), 10)
        h[28:30] = (65535).to_bytes(2, "little")
        self.assertIsNone(frame_fps(h))
