import json
import socket
import threading
import unittest
from unittest.mock import patch
from test_workspace import FakeClient, FakeBackend
from test_account_http import AccountHTTPTests
from okam_bridge.accounts import AccountManager
from okam_bridge.app_server import AppServer
from okam_bridge.controls import build_action, ControlError


class PublicAPITests(AccountHTTPTests):
    def test_root_is_headless_api_and_docs_are_available(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(json.loads(body)["service"], "O-Kam Pro Local Bridge")
        self.assertEqual(self.request("/controls.js")[0], 404)
        self.assertEqual(self.request("/docs/")[0], 200)
        status, _, body = self.request("/openapi.json")
        spec = json.loads(body)
        self.assertTrue(spec["openapi"].startswith("3.1"))
        self.assertIn("/api/cameras/{camera_id}/services", spec["paths"])
        self.assertIn("/api/cameras/{camera_id}/control", spec["paths"])
        self.assertIn("plaintext_password", json.dumps(spec))

    def test_session_bearer_can_use_catalog_and_is_revoked(self):
        status, _, body = self.request(
            "/api/account/login",
            "POST",
            {"username": "first", "password": "valid-test"},
        )
        self.assertEqual(status, 200)
        token = json.loads(body)["session_token"]
        headers = {"Authorization": "Bearer " + token}
        self.assertEqual(self.request("/api/cameras", extra=headers)[0], 200)
        self.assertEqual(
            self.request("/api/account/logout", "POST", {}, extra=headers)[0], 200
        )
        self.assertEqual(self.request("/api/cameras", extra=headers)[0], 401)

    def test_gateway_does_not_trust_spoofed_forwarding_headers(self):
        self.server.token = "gateway-test-abcdefghijkl"
        data = {"username": "first", "password": "valid-test"}
        proxy = {
            "X-Bridge-Gateway": self.server.token,
            "X-Forwarded-Host": "dashboard.example:8100",
            "Origin": "http://dashboard.example:8100",
        }
        self.assertEqual(
            self.request("/api/account/login", "POST", data, extra=proxy)[0], 200
        )
        proxy["Origin"] = "https://evil.example"
        self.assertEqual(
            self.request("/api/account/login", "POST", data, extra=proxy)[0], 403
        )
        proxy["Origin"] = "http://dashboard.example:8100"
        proxy["X-Bridge-Gateway"] = "incorrect"
        self.assertEqual(
            self.request("/api/account/login", "POST", data, extra=proxy)[0], 403
        )

    def test_service_probe_only_selected_known_private_camera(self):
        cookie = self.login("first")
        cid = json.loads(self.request("/api/cameras", cookie=cookie)[2])[0]["id"]
        self.assertEqual(
            self.request("/api/cameras/unknown/services", cookie=cookie)[0], 404
        )
        self.assertEqual(
            self.request("/api/cameras/" + cid + "/services", cookie=cookie)[0], 400
        )
        workspace = self.manager.get(cookie.split("=", 1)[1])
        workspace.records[cid].ip = "192.168.20.10"
        with patch("okam_bridge.services.probe_port", return_value=False) as probe:
            status, _, body = self.request(
                "/api/cameras/" + cid + "/services", cookie=cookie
            )
        self.assertEqual(status, 200)
        value = json.loads(body)
        self.assertEqual(value["camera_id"], cid)
        self.assertFalse(value["configuration"]["onvif"]["writable"])
        self.assertTrue(value["configuration"]["plaintext_password"]["writable"])
        self.assertNotIn(b"native-secret", body)
        self.assertTrue(
            all(call.args[0] == "192.168.20.10" for call in probe.call_args_list)
        )


class PlaintextControlTests(unittest.TestCase):
    def test_documented_external_credentials_command(self):
        action = build_action(
            "plaintext_password", {"enabled": True, "password": "safe&test123"}
        )
        self.assertIn("ExUser=admin&", action["path"])
        self.assertIn("ExPwd=safe%26test123&ExUserSwitch=1&", action["path"])
        self.assertEqual(action["expected"], 0x600E)
        self.assertIn(
            "ExUserSwitch=0&",
            build_action("plaintext_password", {"enabled": False})["path"],
        )
        for invalid in ("short", "a\nbcdefgh", "пароль123"):
            with self.assertRaises(ControlError):
                build_action(
                    "plaintext_password", {"enabled": True, "password": invalid}
                )

    def test_new_password_redacted_even_when_echoed_under_other_key(self):
        from okam_bridge.controls import execute_action
        import struct

        password = "private-test-password"
        body = ('result=0;var value="' + password + '";').encode()

        class Session:
            _channel_buffers = [bytearray()]

            def write(self, *args, **kwargs):
                self._channel_buffers[0].extend(
                    struct.pack("<HHHH", 0x0A01, 0x600E, len(body), 0) + body
                )

            def _pump(self):
                pass

        result = execute_action(
            Session(),
            {"password": "native-test"},
            build_action("plaintext_password", {"enabled": True, "password": password}),
        )
        self.assertEqual(result["state"], "confirmed")
        self.assertNotIn(password, json.dumps(result))


class NativeVerificationTests(unittest.TestCase):
    def test_plaintext_write_reads_back_switch_and_password_presence_without_exposing_value(
        self,
    ):
        from okam_bridge.controls import execute_action
        import struct

        class Session:
            _channel_buffers = [bytearray()]
            paths = []

            def write(self, channel, packet, timeout):
                self.paths.append(packet)
                if b"get_params.cgi?" in packet:
                    code, body = 0x6002, b'var WebPwd="private-new-password";'
                elif b"get_status.cgi?" in packet:
                    code, body = 0x6001, b"result=0;var ExUserSwitch=1;"
                else:
                    code, body = 0x600E, b"result=0;"
                self._channel_buffers[0].extend(
                    struct.pack("<HHHH", 0x0A01, code, len(body), 0) + body
                )

            def _pump(self):
                pass

        session = Session()
        result = execute_action(
            session,
            {"password": "native-test"},
            build_action(
                "plaintext_password",
                {"enabled": True, "password": "private-new-password"},
            ),
        )
        self.assertTrue(result["verification"]["external_access_enabled"])
        self.assertTrue(result["verification"]["web_password_configured"])
        self.assertNotIn("private-new-password", json.dumps(result))
        self.assertEqual(len(session.paths), 3)
