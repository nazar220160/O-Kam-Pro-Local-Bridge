import base64
import hashlib
import http.client
import threading
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from okam_bridge.onvif import ONVIFServer, DiscoveryService

S = "http://www.w3.org/2003/05/soap-envelope"
T = "http://www.onvif.org/ver10/media/wsdl"


class Registry:
    enabled = True

    def __init__(self):
        self.item = dict(
            export_id="cam1",
            camera_id="private",
            name="Garden & Camera",
            advertise_host="127.0.0.1",
            rtsp_port=8554,
            onvif_port=8899,
            username="viewer",
            password="secret",
            ptz=False,
            profiles=[
                dict(
                    token="lens" + str(i),
                    lens=i,
                    width=640,
                    height=480,
                    fps=10,
                    rtsp_uri="rtsp://127.0.0.1:8554/cam1/lens" + str(i),
                    snapshot_uri="http://127.0.0.1:8899/onvif/cam1/snapshot.jpg?lens="
                    + str(i),
                )
                for i in range(2)
            ],
        )

    def get_export(self, key):
        return self.item if self.enabled and key == "cam1" else None

    def list_exports(self):
        return [self.item] if self.enabled else []

    def snapshot(self, key, lens):
        return b"\xff\xd8" + bytes([lens])


class ONVIFTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()
        self.server = ONVIFServer(("127.0.0.1", 0), self.registry)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(
        self,
        action="GetProfiles",
        content="",
        auth=True,
        service="media_service",
        header="",
        raw=None,
        method="POST",
        path=None,
    ):
        namespace = (
            "http://www.onvif.org/ver10/device/wsdl"
            if service == "device_service"
            else T
        )
        body = (
            raw
            if raw is not None
            else f'<s:Envelope xmlns:s="{S}" xmlns:t="{namespace}"><s:Header>{header}</s:Header><s:Body><t:{action}>{content}</t:{action}></s:Body></s:Envelope>'
        )
        headers = {"Content-Type": "application/soap+xml"}
        if auth:
            headers["Authorization"] = (
                "Basic " + base64.b64encode(b"viewer:secret").decode()
            )
        c = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        c.request(method, path or "/onvif/cam1/" + service, body, headers)
        r = c.getresponse()
        result = (r.status, dict(r.getheaders()), r.read())
        c.close()
        return result

    def test_profiles_and_lens_mapping(self):
        self.assertEqual(self.request(auth=False)[0], 401)
        status, _, data = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(
            [
                n.attrib["token"]
                for n in ET.fromstring(data).iter("{" + T + "}Profiles")
            ],
            ["lens0", "lens1"],
        )
        self.assertNotIn(b"secret", data)
        self.assertIn(
            b"/cam1/lens1",
            self.request("GetStreamUri", "<t:ProfileToken>lens1</t:ProfileToken>")[2],
        )
        self.assertEqual(
            self.request("GetStreamUri", "<t:ProfileToken>invalid</t:ProfileToken>")[0],
            400,
        )

    def test_snapshot_revocation(self):
        path = "/onvif/cam1/snapshot.jpg?lens=1"
        self.assertEqual(self.request(method="GET", path=path, auth=False)[0], 401)
        self.assertEqual(self.request(method="GET", path=path)[2], b"\xff\xd8\x01")
        self.registry.enabled = False
        self.assertEqual(self.request()[0], 404)

    def test_xml_and_metadata_auth(self):
        self.assertEqual(
            self.request("GetSystemDateAndTime", auth=False, service="device_service")[
                0
            ],
            200,
        )
        self.assertEqual(
            self.request("GetCapabilities", auth=False, service="device_service")[0],
            401,
        )
        self.assertEqual(self.request("Reboot")[0], 400)
        self.assertEqual(
            self.request(raw='<!DOCTYPE x [<!ENTITY e "evil">]><x>&e;</x>')[0], 400
        )
        self.assertEqual(self.request(raw="x" * 65537)[0], 413)
        self.assertNotIn(
            b"ptz_service", self.request("GetServices", service="device_service")[2]
        )

    def test_ws_security(self):
        def token(created):
            nonce = b"nonce"
            digest = base64.b64encode(
                hashlib.sha1(nonce + created.encode() + b"secret").digest()
            ).decode()
            return f'<w:Security xmlns:w="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" xmlns:u="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"><w:UsernameToken><w:Username>viewer</w:Username><w:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</w:Password><w:Nonce>{base64.b64encode(nonce).decode()}</w:Nonce><u:Created>{created}</u:Created></w:UsernameToken></w:Security>'

        self.assertEqual(
            self.request(
                auth=False, header=token(datetime.now(timezone.utc).isoformat())
            )[0],
            200,
        )
        self.assertEqual(
            self.request(auth=False, header=token("2000-01-01T00:00:00Z"))[0], 401
        )

    def test_http_digest(self):
        from urllib.request import (
            HTTPPasswordMgrWithDefaultRealm,
            HTTPDigestAuthHandler,
            build_opener,
        )

        url = "http://%s:%s/onvif/cam1/snapshot.jpg?lens=0" % self.server.server_address
        mgr = HTTPPasswordMgrWithDefaultRealm()
        mgr.add_password(None, url, "viewer", "secret")
        with build_opener(HTTPDigestAuthHandler(mgr)).open(url, timeout=3) as r:
            self.assertEqual(r.read(), b"\xff\xd8\x00")

    def test_discovery(self):
        discovery = DiscoveryService(self.registry, port=0)
        probe = b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" xmlns:n="http://www.onvif.org/ver10/network/wsdl"><s:Header><a:MessageID>uuid:test</a:MessageID></s:Header><s:Body><d:Probe><d:Types>n:NetworkVideoTransmitter</d:Types></d:Probe></s:Body></s:Envelope>'
        data = discovery.build_response(probe)
        ET.fromstring(data)
        self.assertIn(b"/onvif/cam1/device_service", data)
        self.assertIsNone(
            discovery.build_response(
                probe.replace(b"n:NetworkVideoTransmitter", b"n:Other")
            )
        )
        self.registry.enabled = False
        self.assertIsNone(discovery.build_response(probe))

    def test_service_action_namespace_is_checked(self):
        raw = f'<s:Envelope xmlns:s="{S}" xmlns:t="{T}"><s:Body><t:GetSystemDateAndTime/></s:Body></s:Envelope>'
        self.assertEqual(
            self.request(raw=raw, auth=False, service="device_service")[0], 400
        )

    def test_wrong_credentials_and_encoded_entity_rejected(self):
        self.registry.item["password"] = "changed"
        self.assertEqual(self.request()[0], 401)
        malicious = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY e "evil">]><x>&e;</x>'.encode(
            "utf-16"
        )
        self.assertEqual(self.request(raw=malicious)[0], 400)

    def test_discovery_busy_is_a_notice(self):
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as occupied:
            occupied.bind(("", 0))
            discovery = DiscoveryService(self.registry, port=occupied.getsockname()[1])
            discovery.start()
            self.assertTrue(discovery.error)
            discovery.close()
