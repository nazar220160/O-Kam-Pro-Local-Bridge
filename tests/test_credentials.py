import unittest
from urllib.parse import parse_qs
from okam_bridge.transport import make_request


class CredentialsTests(unittest.TestCase):
    def test_camera_password_used_in_both_protocol_fields(self):
        request = make_request(
            "livestream.cgi?streamid=10&substream=2&", "admin", "new-password"
        )
        query = parse_qs(request[8:].decode().partition("?")[2])
        self.assertEqual(query["loginpas"], ["new-password"])
        self.assertEqual(query["pwd"], ["new-password"])

    def test_password_cannot_inject_parameters(self):
        request = make_request("get_status.cgi?name=admin&", "admin", "p&x=1")
        query = parse_qs(request[8:].decode().partition("?")[2])
        self.assertEqual(query["pwd"], ["p&x=1"])
        self.assertNotIn("x", query)
