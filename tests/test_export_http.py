import base64, http.client, json, threading, unittest
from okam_bridge.accounts import AccountManager
from okam_bridge.app_server import AppServer
from test_workspace import FakeClient, FakeBackend, FakeCamera
from test_exports import FakePublisher


class ExportHTTPTests(unittest.TestCase):
    def setUp(self):
        self.manager = AccountManager(FakeClient, FakeBackend())
        self.server = AppServer(("127.0.0.1", 0), self.manager)
        self.server.exports.probe = lambda: True
        self.server.exports.publisher_factory = FakePublisher
        self.t = threading.Thread(target=self.server.serve_forever)
        self.t.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.t.join()

    def req(self, path, method="GET", body=None, cookie=None, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        if cookie:
            h["Cookie"] = cookie
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        conn.request(method, path, json.dumps(body) if body is not None else None, h)
        r = conn.getresponse()
        data = r.read()
        out = (r.status, dict(r.getheaders()), data)
        conn.close()
        return out

    def login(self, name):
        code, h, b = self.req(
            "/api/account/login", "POST", {"username": name, "password": "valid-test"}
        )
        self.assertEqual(code, 200)
        cookie = h["Set-Cookie"].split(";")[0]
        workspace = self.manager.get(cookie.split("=", 1)[1])
        cid = next(iter(workspace.records))
        workspace.cameras[cid] = FakeCamera({"name": "Example"})
        workspace.records[cid].ip = "192.168.20.10"
        return cookie, workspace, cid

    def test_export_routes_do_not_mutate_native_settings_and_hide_credentials(self):
        cookie, w, cid = self.login("first")
        base = "/api/cameras/" + cid + "/export"
        self.assertEqual(self.req(base)[0], 401)
        code, h, body = self.req(
            base,
            "POST",
            {"enabled": True, "advertise_host": "192.168.20.1", "onvif": False},
            cookie,
        )
        self.assertEqual(code, 200)
        self.assertIn("Max-Age=31536000", h["Set-Cookie"])
        status = json.loads(body)
        self.assertTrue(status["enabled"])
        self.assertEqual(len(status["profiles"]), 3)
        self.assertEqual(self.req(base + "/credentials", cookie=cookie)[0], 404)
        code, _, b = self.req(base + "/credentials", "POST", {}, cookie)
        self.assertEqual(code, 200)
        creds = json.loads(b)
        self.assertNotIn(creds["password"], body.decode())
        self.assertNotIn(
            creds["password"], self.req("/api/cameras", cookie=cookie)[2].decode()
        )
        callback = {
            "protocol": "rtsp",
            "action": "read",
            "path": status["export_id"] + "/lens0",
            "user": creds["username"],
            "password": creds["password"],
        }
        self.assertEqual(self.req("/api/exports/auth", "POST", callback)[0], 200)
        self.req("/api/account/logout", "POST", {}, cookie)
        self.assertEqual(self.req("/api/exports/auth", "POST", callback)[0], 401)

    def test_other_account_and_media_player_cannot_configure_publication(self):
        cookie, w, cid = self.login("first")
        other, _, _ = self.login("second")
        base = "/api/cameras/" + cid + "/export"
        self.assertEqual(
            self.req(
                base,
                "POST",
                {"enabled": True, "advertise_host": "192.168.20.1", "onvif": False},
                cookie,
            )[0],
            200,
        )
        self.assertFalse(json.loads(self.req(base, cookie=other)[2])["enabled"])
        auth = (
            "Basic " + base64.b64encode(("player:" + w.player_token).encode()).decode()
        )
        self.assertEqual(
            self.req(
                base + "/credentials", "POST", {}, headers={"Authorization": auth}
            )[0],
            401,
        )
        self.assertEqual(
            self.req(base, "POST", {"enabled": False}, headers={"Authorization": auth})[
                0
            ],
            401,
        )
