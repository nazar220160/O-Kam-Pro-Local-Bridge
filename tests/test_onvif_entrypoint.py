"""Host/port clients select a publication through its credentials, not a URL path."""

import base64
import http.client
import threading
import unittest

from okam_bridge.onvif import ONVIFServer
from test_onvif import Registry, S


class EntryPointTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()
        self.second = {
            **self.registry.item,
            "export_id": "cam2",
            "name": "Second camera",
            "password": "second-secret",
        }
        self.registry.list_exports = lambda: (
            [self.registry.item, self.second] if self.registry.enabled else []
        )
        self.server = ONVIFServer(("127.0.0.1", 0), self.registry)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, action, password=None, path="/onvif/device_service"):
        body = f'<s:Envelope xmlns:s="{S}" xmlns:t="http://www.onvif.org/ver10/device/wsdl"><s:Body><t:{action}/></s:Body></s:Envelope>'
        headers = {"Content-Type": "application/soap+xml"}
        if password is not None:
            headers["Authorization"] = (
                "Basic " + base64.b64encode(("viewer:" + password).encode()).decode()
            )
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        conn.request("POST", path, body, headers)
        response = conn.getresponse()
        out = (response.status, dict(response.getheaders()), response.read())
        conn.close()
        return out

    def test_standard_path_selects_correct_camera_by_credentials(self):
        status, _, body = self.request("GetDeviceInformation", "second-secret")
        self.assertEqual(status, 200)
        self.assertIn(b"cam2", body)
        self.assertNotIn(b"cam1", body)
        status, _, body = self.request("GetCapabilities", "secret")
        self.assertEqual(status, 200)
        self.assertIn(b"/onvif/cam1/media_service", body)
        self.assertNotIn(b"/onvif/cam2/", body)

    def test_standard_path_challenges_unknown_credentials_and_revokes_access(self):
        for password in (None, "incorrect"):
            status, headers, body = self.request("GetDeviceInformation", password)
            self.assertEqual(status, 401)
            self.assertIn("Digest", headers["WWW-Authenticate"])
            self.assertNotIn(b"cam1", body)
            self.assertNotIn(b"cam2", body)
        self.registry.enabled = False
        self.assertEqual(self.request("GetDeviceInformation", "secret")[0], 401)
        self.assertEqual(
            self.request(
                "GetDeviceInformation", "secret", "/onvif/cam1/device_service"
            )[0],
            404,
        )

    def test_bootstrap_clock_discloses_no_publication_metadata(self):
        status, _, body = self.request("GetSystemDateAndTime")
        self.assertEqual(status, 200)
        self.assertIn(b"UTCDateTime", body)
        self.assertNotIn(b"cam1", body)
        self.assertNotIn(b"cam2", body)

    def test_independent_client_selects_publication_with_wsse_and_http_digest(self):
        try:
            import onvif
            from pathlib import Path
            from zeep import Client
            from zeep.wsse.username import UsernameToken
            from zeep.transports import Transport
            import requests
            from requests.auth import HTTPDigestAuth
        except ImportError:
            self.skipTest("Install requirements-dev.txt for independent ONVIF client")
        wsdl = Path(onvif.__file__).resolve().parent.parent / "wsdl/devicemgmt.wsdl"
        url = "http://%s:%s/onvif/device_service" % self.server.server_address
        for digest in (False, True):
            with self.subTest(http_digest=digest), requests.Session() as session:
                if digest:
                    session.auth = HTTPDigestAuth("viewer", "second-secret")
                client = Client(
                    str(wsdl),
                    transport=Transport(session=session, operation_timeout=3),
                    wsse=(
                        None
                        if digest
                        else UsernameToken("viewer", "second-secret", use_digest=True)
                    ),
                )
                service = client.create_service(
                    "{http://www.onvif.org/ver10/device/wsdl}DeviceBinding", url
                )
                self.assertEqual(service.GetDeviceInformation().SerialNumber, "cam2")
