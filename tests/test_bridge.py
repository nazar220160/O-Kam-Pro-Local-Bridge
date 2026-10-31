import base64
import http.client
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from okam_bridge.config import load_config, save_config, validate_config
from okam_bridge.camera import Fanout
from okam_bridge.transport import connect_lan
from okam_bridge.web import BridgeServer
from okam_bridge.vendor.cs2 import encode_uid, encrypt_packet, decrypt_packet

ENTRY = {
    "id": "yard",
    "name": "Yard <test>",
    "ip": "127.0.0.1",
    "transport_uid": "ABCD123456ABCDE",
    "service_parameter": "unused",
    "password_env": "TEST_CAMERA_SECRET",
}


class ConfigTests(unittest.TestCase):
    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            validate_config({"cameras": [ENTRY, ENTRY]})

    def test_missing_env_is_actionable_without_secret(self):
        os.environ.pop("TEST_CAMERA_SECRET", None)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            save_config(p, {"cameras": [ENTRY]})
            with self.assertRaisesRegex(ValueError, "TEST_CAMERA_SECRET"):
                load_config(p)

    def test_private_roundtrip_and_redaction(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            c = dict(ENTRY, password="private-example")
            c.pop("password_env")
            save_config(p, {"cameras": [c]})
            cfg = load_config(p)
            self.assertEqual(cfg["cameras"][0]["password"], "private-example")
            if os.name != "nt":
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_public_bind_requires_token(self):
        with self.assertRaisesRegex(ValueError, "token"):
            validate_config({"listen": "0.0.0.0", "cameras": [ENTRY]})

    def test_invalid_ip_and_path_id_rejected(self):
        for k, v in [("id", "../x"), ("ip", "example.com")]:
            with self.subTest(k=k), self.assertRaises(ValueError):
                validate_config({"cameras": [dict(ENTRY, **{k: v})]})


class FanoutTests(unittest.TestCase):
    def test_two_viewers_and_slow_consumer(self):
        f = Fanout(capacity=2)
        a = f.subscribe()
        b = f.subscribe()
        f.publish(b"one")
        self.assertEqual(a.get(0.1), b"one")
        self.assertEqual(b.get(0.1), b"one")
        f.publish(b"two")
        f.publish(b"three")
        f.publish(b"four")
        self.assertIsNone(a.get(0.1))
        f.unsubscribe(a)
        f.unsubscribe(b)
        self.assertEqual(f.count, 0)

    def test_close_wakes_waiter(self):
        f = Fanout()
        a = f.subscribe()
        f.close()
        self.assertIsNone(a.get(0.1))


class DiscoveryTests(unittest.TestCase):
    def test_encrypted_discovery_and_identity_check(self):
        # A real UDP peer ignores clear packets and sends a wrong UID before
        # the correct UID. Accepting the first arbitrary reply is a regression.
        uid = "ABCD123456ABCDE"
        key = "test-key"
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(2)
        port = sock.getsockname()[1]

        def peer():
            try:
                while True:
                    b, addr = sock.recvfrom(4096)
                    clear = decrypt_packet(key, b)
                    if clear[:2] == b"\xf1\x30":
                        sock.sendto(
                            encrypt_packet(
                                key, b"\xf1\x42\x00\x14" + encode_uid("WXYZ654321ZYXWV")
                            ),
                            addr,
                        )
                        sock.sendto(
                            encrypt_packet(key, b"\xf1\x42\x00\x14" + encode_uid(uid)),
                            addr,
                        )
                        return
            finally:
                sock.close()

        t = threading.Thread(target=peer)
        t.start()
        s = connect_lan(
            {
                "ip": "127.0.0.1",
                "transport_uid": uid,
                "service_parameter": "EBGDEOBOKGICGAIAFF:test-key",
                "ports": [port],
            },
            timeout=1,
        )
        self.assertEqual(s._peer, ("127.0.0.1", port))
        s.close()
        t.join()


class FakeCamera:
    name = "Yard <script>alert(1)</script>"

    def status(self):
        return {"state": "idle", "viewers": 0, "last_error": None}

    def frames(self, kind):
        yield b"\xff\xd8test\xff\xd9" if kind == "jpeg" else b"\x00\x00\x00\x01\x67test"

    def stop(self):
        pass


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = BridgeServer(
            ("127.0.0.1", 0), {"yard": FakeCamera()}, token="correct-secret"
        )
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, auth=False, method="GET", body=None, headers=None):
        h = dict(headers or {})
        if auth:
            h["Authorization"] = (
                "Basic " + base64.b64encode(b"bridge:correct-secret").decode()
            )
        c = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        c.request(method, path, body, h)
        r = c.getresponse()
        data = r.read()
        result = (r.status, dict(r.getheaders()), data)
        c.close()
        return result

    def test_status_requires_auth_and_does_not_expose_secrets(self):
        self.assertEqual(self.request("/api/cameras")[0], 401)
        status, _, data = self.request("/api/cameras", True)
        self.assertEqual(status, 200)
        self.assertNotIn(b"correct-secret", data)
        self.assertNotIn(b"transport_uid", data)

    def test_static_config_mode_is_also_headless_and_snapshot_works(self):
        status, headers, body = self.request("/", True)
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(json.loads(body)["mode"], "static-config")
        status, h, data = self.request("/api/cameras/yard/snapshot.jpg", True)
        self.assertEqual(status, 200)
        self.assertEqual(h["Content-Type"], "image/jpeg")
        self.assertTrue(data.startswith(b"\xff\xd8"))

    def test_login_cookie_and_url_token_rejected(self):
        self.assertEqual(self.request("/api/cameras?token=correct-secret")[0], 401)
        status, h, _ = self.request(
            "/login",
            method="POST",
            body="token=correct-secret",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(status, 303)
        self.assertIn("HttpOnly", h["Set-Cookie"])
        cookie = h["Set-Cookie"].split(";")[0]
        self.assertEqual(
            self.request("/api/cameras", headers={"Cookie": cookie})[0], 200
        )

    def test_unknown_camera_is_404(self):
        self.assertEqual(
            self.request("/api/cameras/missing/snapshot.jpg", True)[0], 404
        )


if __name__ == "__main__":
    unittest.main()
