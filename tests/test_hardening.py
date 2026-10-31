import http.client
import threading
import unittest
from test_bridge import ENTRY, FakeCamera
from okam_bridge.config import validate_config
from okam_bridge.camera import GopCache
from okam_bridge.web import BridgeServer


class HardeningTests(unittest.TestCase):
    def test_bad_scalar_types_fail_before_startup(self):
        for change in ({"access_token": 12}, {"idle_timeout": "bad"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_config({"cameras": [ENTRY], **change})
        with self.assertRaises(ValueError):
            validate_config({"cameras": [dict(ENTRY, password=123)]})

    def test_loopback_rejects_foreign_host(self):
        s = BridgeServer(("127.0.0.1", 0), {"yard": FakeCamera()})
        t = threading.Thread(target=s.serve_forever)
        t.start()
        try:
            c = http.client.HTTPConnection(*s.server_address)
            c.request("GET", "/api/cameras", headers={"Host": "evil.example"})
            r = c.getresponse()
            self.assertEqual(r.status, 403)
            r.read()
            c.close()
        finally:
            s.shutdown()
            s.server_close()
            t.join()

    def test_parameter_sets_survive_separate_idr(self):
        g = GopCache()
        sps = b"\x00\x00\x00\x01\x67sps"
        pps = b"\x00\x00\x00\x01\x68pps"
        idr = b"\x00\x00\x00\x01\x65idr"
        g.append(sps)
        g.append(pps)
        g.append(idr)
        self.assertEqual(bytes(g), sps + pps + idr)
