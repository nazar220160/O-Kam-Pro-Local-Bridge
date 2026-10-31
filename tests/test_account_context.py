import struct
import unittest
from urllib.parse import parse_qs
from okam_bridge.transport import make_request


class AccountContextTests(unittest.TestCase):
    def test_preserves_the_shared_viewers_account_identifier(self):
        request = make_request(
            "livestream.cgi?streamid=10&substream=1&",
            "admin",
            "camera-native",
            "888888",
            account_id="123456789",
        )
        q = parse_qs(request[8:].decode().partition("?")[2])
        self.assertEqual(q["userId"], ["123456789"])
        self.assertEqual(q["loginpas"], ["camera-native"])
        self.assertEqual(struct.unpack("<HHHH", request[:8])[2], len(request) - 8)

    def test_rejects_invalid_account_identifier(self):
        with self.assertRaises(ValueError):
            make_request(
                "get_status.cgi?", "admin", "native", account_id="123&userId=456"
            )
