import json
import unittest
from unittest.mock import Mock, patch

from okam_bridge.exports import ExportError, publication_request_host
import test_exports as export_fixture
import test_export_http as http_fixture


class CloudExportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = export_fixture.ExportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.workspace = self.fixture.w
        self.cid = self.fixture.cid
        self.registry = self.fixture.registry
        self.workspace.records[self.cid].connection_mode = "cloud"
        self.workspace.records[self.cid].ip = None

    def test_cloud_without_ip_uses_bridge_host_and_persists_it(self):
        with patch("okam_bridge.exports.socket.socket") as socket:
            status = self.registry.configure(
                self.workspace,
                self.cid,
                {"enabled": True, "onvif": False},
                request_host="192.168.20.1",
            )
        socket.assert_not_called()
        self.assertEqual(status["advertise_host"], "192.168.20.1")
        self.assertEqual(
            self.workspace.saved_exports[self.cid]["advertise_host"], "192.168.20.1"
        )
        for profile in status["profiles"]:
            self.assertTrue(profile["rtsp_uri"].startswith("rtsp://192.168.20.1:"))

    def test_cloud_does_not_route_toward_stale_remote_lan_hint(self):
        self.workspace.records[self.cid].ip = "192.168.99.20"
        with patch("okam_bridge.exports.socket.socket") as socket:
            host = self.registry._host(
                self.workspace, self.cid, None, "bridge.example.test"
            )
        socket.assert_not_called()
        self.assertEqual(host, "bridge.example.test")

    def test_explicit_and_saved_host_win_without_changing_publication_credentials(self):
        options = {"enabled": True, "onvif": False}
        first = self.registry.configure(
            self.workspace,
            self.cid,
            {**options, "advertise_host": "nvr.example.test"},
            request_host="panel.example.test",
        )
        credentials = self.registry.credentials(self.workspace, self.cid)
        second = self.registry.configure(
            self.workspace,
            self.cid,
            options,
            request_host="different-panel.example.test",
        )
        self.assertEqual(second["advertise_host"], "nvr.example.test")
        self.assertEqual(first["export_id"], second["export_id"])
        self.assertEqual(
            self.registry.credentials(self.workspace, self.cid), credentials
        )
        # Restart restoration has no HTTP request, so it must use saved state.
        self.registry.disable(self.workspace, self.cid)
        third = self.registry.configure(self.workspace, self.cid, options)
        self.assertEqual(third["advertise_host"], "nvr.example.test")
        self.assertEqual(third["export_id"], first["export_id"])

    def test_lan_keeps_interface_inference_for_first_publication(self):
        self.workspace.records[self.cid].connection_mode = "lan"
        self.workspace.records[self.cid].ip = "192.168.20.10"
        with patch("okam_bridge.exports.socket.socket") as socket:
            sock = socket.return_value.__enter__.return_value
            sock.getsockname.return_value = ("192.168.20.1", 41000)
            host = self.registry._host(
                self.workspace, self.cid, None, "panel.example.test"
            )
        sock.connect.assert_called_once_with(("192.168.20.10", 9))
        self.assertEqual(host, "192.168.20.1")

    def test_no_available_bridge_host_requests_explicit_host(self):
        with self.assertRaisesRegex(ExportError, "^advertise_host_required$"):
            self.registry.configure(self.workspace, self.cid, {"enabled": True})


class PublicationAuthorityTests(unittest.TestCase):
    def test_port_is_removed_and_dns_is_supported(self):
        for authority, host in (
            ("192.168.20.1:8080", "192.168.20.1"),
            ("Bridge.Example.test:443", "bridge.example.test"),
            ("bridge", "bridge"),
        ):
            self.assertEqual(publication_request_host(authority), host)

    def test_invalid_or_loopback_authorities_are_not_inferred(self):
        for value in (
            None,
            "",
            "127.0.0.1:8098",
            "localhost:8080",
            "localhost.:8080",
            "127.0.0.1.:8080",
            "0.0.0.0:8080",
            "user:password@host",
            "host/path",
            "host?x",
            "host#x",
            "host,other",
            "http://host",
            "host:99999",
            "host:0",
            "host\t",
            "[::1]:8080",
        ):
            with self.subTest(value=value):
                self.assertIsNone(publication_request_host(value))


class CloudExportHTTPTests(unittest.TestCase):
    def setUp(self):
        self.fixture = http_fixture.ExportHTTPTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.cookie, self.workspace, self.cid = self.fixture.login("first")
        self.fixture.server.token = "test-private-gateway-token"
        self.fixture.server.exports._ensure_onvif = Mock()
        self.workspace.cameras[self.cid].control = Mock(
            return_value={"state": "confirmed", "parameters": {}}
        )
        self.workspace.records[self.cid].connection_mode = "cloud"
        self.workspace.records[self.cid].ip = None
        self.route = "/api/cameras/" + self.cid + "/export"

    def test_authenticated_gateway_host_enables_cloud_onvif_without_camera_ip(self):
        code, _, body = self.fixture.req(
            self.route,
            "POST",
            {"enabled": True, "rtsp": True, "onvif": True},
            self.cookie,
            headers={
                "X-Bridge-Gateway": self.fixture.server.token,
                "X-Forwarded-Host": "192.168.20.1:8080",
            },
        )
        self.assertEqual(code, 200, body)
        status = json.loads(body)
        self.assertTrue(status["onvif"])
        self.assertEqual(status["advertise_host"], "192.168.20.1")
        self.assertTrue(status["onvif_uri"].startswith("http://192.168.20.1:8899/"))
        self.assertEqual(len(status["profiles"]), 3)

    def test_forwarded_host_from_direct_client_is_ignored(self):
        # Bearer authorizes the account API but is not the private web gateway.
        token = self.cookie.split("=", 1)[1]
        code, _, body = self.fixture.req(
            self.route,
            "POST",
            {"enabled": True},
            headers={
                "Authorization": "Bearer " + token,
                "X-Forwarded-Host": "attacker.example.test:8080",
            },
        )
        self.assertEqual(code, 400, body)
        self.assertEqual(json.loads(body)["error"], "advertise_host_required")
        self.assertFalse(self.workspace.saved_exports)
