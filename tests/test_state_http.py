import tempfile
import threading
import unittest
import test_account_http as helpers
from test_workspace import FakeClient, FakeBackend
from okam_bridge.accounts import AccountManager
from okam_bridge.app_server import AppServer


class PersistentHTTPTests(unittest.TestCase):
    request = helpers.AccountHTTPTests.request
    login = helpers.AccountHTTPTests.login

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.start_api()

    def start_api(self):
        self.manager = AccountManager(FakeClient, FakeBackend())
        self.server = AppServer(
            ("127.0.0.1", 0), self.manager, state_dir=self.temp.name
        )
        self.t = threading.Thread(target=self.server.serve_forever)
        self.t.start()

    def stop_api(self):
        self.server.shutdown()
        self.server.server_close()
        self.t.join()

    def tearDown(self):
        self.stop_api()
        self.temp.cleanup()

    def test_existing_browser_cookie_works_after_api_restart(self):
        cookie = self.login("first")
        self.stop_api()
        self.start_api()
        code, headers, body = self.request("/api/account", cookie=cookie)
        self.assertEqual(code, 200)
        self.assertIn("Max-Age=31536000", headers["Set-Cookie"])
        self.assertIn(b"first", body)
        code, headers, _ = self.request(
            "/api/account/login",
            "POST",
            {"username": "first", "password": "valid-test"},
            cookie=cookie,
        )
        self.assertEqual(code, 200)
        self.assertEqual(headers["Set-Cookie"].split(";")[0], cookie)
        self.assertEqual(self.request("/api/cameras", cookie=cookie)[0], 200)

    def test_explicit_logout_is_still_revoked_after_restart(self):
        cookie = self.login("first")
        self.assertEqual(
            self.request("/api/account/logout", "POST", {}, cookie)[0], 200
        )
        self.stop_api()
        self.start_api()
        self.assertEqual(self.request("/api/account", cookie=cookie)[0], 401)
