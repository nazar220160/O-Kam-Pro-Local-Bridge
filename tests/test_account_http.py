import http.client
import json
import threading
import unittest
from test_workspace import FakeClient, FakeBackend
from okam_bridge.accounts import AccountManager
from okam_bridge.app_server import AppServer


class AccountHTTPTests(unittest.TestCase):
    def setUp(self):
        self.manager = AccountManager(FakeClient, FakeBackend())
        self.server = AppServer(("127.0.0.1", 0), self.manager)
        self.t = threading.Thread(target=self.server.serve_forever)
        self.t.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.manager.close()
        self.t.join()

    def request(self, path, method="GET", data=None, cookie=None, extra=None):
        h = {"Content-Type": "application/json"}
        if cookie:
            h["Cookie"] = cookie
        h.update(extra or {})
        c = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        c.request(method, path, json.dumps(data) if data is not None else None, h)
        r = c.getresponse()
        b = r.read()
        out = (r.status, dict(r.getheaders()), b)
        c.close()
        return out

    def login(self, user):
        status, h, b = self.request(
            "/api/account/login", "POST", {"username": user, "password": "valid-test"}
        )
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", h["Set-Cookie"])
        return h["Set-Cookie"].split(";")[0]

    def test_root_has_real_account_login_not_fixed_camera(self):
        status, _, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("O-Kam Pro".encode(), body)
        self.assertNotIn(b"192.168.20.11", body)
        self.assertEqual(self.request("/api/cameras")[0], 401)

    def test_cookies_isolate_accounts_and_secrets(self):
        a = self.login("first")
        b = self.login("second")
        self.assertIn(b"first camera", self.request("/api/cameras", cookie=a)[2])
        self.assertNotIn(b"second camera", self.request("/api/cameras", cookie=a)[2])
        self.assertIn(b"second camera", self.request("/api/cameras", cookie=b)[2])
        self.assertNotIn(b"native-secret", self.request("/api/cameras", cookie=a)[2])

    def test_json_origin_and_host_checks(self):
        data = {"username": "first", "password": "valid-test"}
        self.assertEqual(
            self.request(
                "/api/account/login",
                "POST",
                data,
                extra={"Origin": "http://evil.example"},
            )[0],
            403,
        )
        self.assertEqual(
            self.request(
                "/api/account/login", "POST", data, extra={"Content-Type": "text/plain"}
            )[0],
            415,
        )
        self.assertEqual(self.request("/", extra={"Host": "evil.example"})[0], 403)

    def test_logout_revokes_catalog_and_stream_access(self):
        cookie = self.login("first")
        self.assertEqual(
            self.request("/api/account/logout", "POST", {}, cookie)[0], 200
        )
        self.assertEqual(self.request("/api/cameras", cookie=cookie)[0], 401)

    def test_unknown_camera_cannot_be_connected(self):
        cookie = self.login("first")
        self.assertEqual(
            self.request("/api/cameras/unknown/connect", "POST", {}, cookie)[0], 404
        )

    def test_public_ip_override_rejected(self):
        cookie = self.login("first")
        cid = json.loads(self.request("/api/cameras", cookie=cookie)[2])[0]["id"]
        self.assertEqual(
            self.request(
                "/api/cameras/" + cid + "/connect", "POST", {"ip": "8.8.8.8"}, cookie
            )[0],
            400,
        )


class PlayerHTTPTests(AccountHTTPTests):
    def test_player_basic_auth_is_media_only_and_revoked_at_logout(self):
        import base64

        cookie = self.login("first")
        status, _, data = self.request("/api/account/player", cookie=cookie)
        self.assertEqual(status, 200)
        credentials = json.loads(data)
        self.assertNotIn("valid-test", data.decode())
        self.assertNotIn("native-secret", data.decode())
        auth = (
            "Basic "
            + base64.b64encode(
                (credentials["username"] + ":" + credentials["password"]).encode()
            ).decode()
        )
        workspace = self.manager.get(cookie.split("=", 1)[1])
        cid = workspace.catalog()[0]["id"]
        from test_workspace import FakeCamera

        workspace.cameras[cid] = FakeCamera({"name": "Any camera"})
        self.assertEqual(
            self.request(
                "/api/cameras/" + cid + "/snapshot.jpg", extra={"Authorization": auth}
            )[0],
            200,
        )
        self.assertEqual(
            self.request("/api/account", extra={"Authorization": auth})[0], 401
        )
        self.request("/api/account/logout", "POST", {}, cookie)
        self.assertEqual(
            self.request(
                "/api/cameras/" + cid + "/snapshot.jpg", extra={"Authorization": auth}
            )[0],
            401,
        )

    def test_bridge_gate_still_challenges_player_and_accepts_scoped_credentials(self):
        import base64

        cookie = self.login("first")
        w = self.manager.get(cookie.split("=", 1)[1])
        cid = w.catalog()[0]["id"]
        from test_workspace import FakeCamera

        w.cameras[cid] = FakeCamera({"name": "Any camera"})
        self.server.token = "test-bridge-token-123456"
        path = "/api/cameras/" + cid + "/snapshot.jpg"
        status, headers, _ = self.request(path)
        self.assertEqual(status, 401)
        self.assertIn("Basic", headers.get("WWW-Authenticate", ""))
        auth = (
            "Basic " + base64.b64encode(("player:" + w.player_token).encode()).decode()
        )
        self.assertEqual(self.request(path, extra={"Authorization": auth})[0], 200)

    def test_quality_http_request_reaches_selected_camera(self):
        import time

        cookie = self.login("first")
        cid = json.loads(self.request("/api/cameras", cookie=cookie)[2])[0]["id"]
        route = "/api/cameras/" + cid + "/connect"
        self.assertEqual(
            self.request(route, "POST", {"quality": "invalid"}, cookie)[0], 400
        )
        self.assertEqual(
            self.request(
                route, "POST", {"quality": "low", "ip": "192.168.20.10"}, cookie
            )[0],
            202,
        )
        workspace = self.manager.get(cookie.split("=", 1)[1])
        for _ in range(100):
            if cid in workspace.cameras:
                break
            time.sleep(0.01)
        self.assertEqual(workspace.cameras[cid].config["quality"], "low")
        self.assertEqual(
            json.loads(self.request("/api/cameras", cookie=cookie)[2])[0]["quality"],
            "low",
        )

    def test_native_camera_password_is_explicit_post_only_and_not_in_metadata(self):
        cookie = self.login("first")
        cid = json.loads(self.request("/api/cameras", cookie=cookie)[2])[0]["id"]
        base = "/api/cameras/" + cid
        self.assertEqual(self.request(base + "/credentials")[0], 401)
        self.assertNotEqual(self.request(base + "/credentials", cookie=cookie)[0], 200)
        status, _, body = self.request(base + "/credentials", "POST", {}, cookie)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["password"], "native-secret")
        status, _, body = self.request(base + "/details", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertNotIn(b"native-secret", body)
        self.assertEqual(
            self.request(
                base + "/control",
                "POST",
                {"action": "ptz", "args": {"direction": "up"}},
                cookie,
            )[0],
            400,
        )

    def test_player_cannot_reveal_camera_password_or_control(self):
        import base64

        cookie = self.login("first")
        w = self.manager.get(cookie.split("=", 1)[1])
        cid = w.catalog()[0]["id"]
        auth = (
            "Basic " + base64.b64encode(("player:" + w.player_token).encode()).decode()
        )
        for endpoint in ("credentials", "control"):
            self.assertEqual(
                self.request(
                    "/api/cameras/" + cid + "/" + endpoint,
                    "POST",
                    {},
                    extra={"Authorization": auth},
                )[0],
                401,
            )
