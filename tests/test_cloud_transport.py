import socket
import threading
import unittest
from unittest.mock import Mock, patch

from okam_bridge.camera import Camera
from okam_bridge.sd_archive import SDSession
from okam_bridge.transport import (
    CloudSession,
    connect_camera,
    connect_cloud,
)
from okam_bridge.vendor.cs2 import CS2Error, encode_uid


CONFIG = {
    "id": "test",
    "transport_uid": "ABCD123456ABCDE",
    "service_parameter": "EBGDEOBOKGICGAIAFF:test-key",
    "connection_mode": "cloud",
}


class RelaySocket:
    def __init__(self, packets=()):
        self.packets = list(packets)
        self.sent = []
        self.closed = False

    def getsockname(self):
        return "192.0.2.10", 41000

    def recvfrom(self, size):
        if not self.packets:
            raise socket.timeout()
        return self.packets.pop(0)

    def sendto(self, packet, address):
        self.sent.append((packet, address))
        return len(packet)

    def close(self):
        self.closed = True


class CloudTransportTests(unittest.TestCase):
    def test_relay_readiness_is_required_and_lan_ip_is_ignored(self):
        direct = ("192.0.2.55", 32108)
        relay = ("203.0.113.20", 33000)
        uid = encode_uid(CONFIG["transport_uid"])
        sock = RelaySocket(
            [
                (b"\xf1\x42\x00\x14" + uid, direct),
                (
                    b"\xf1\x84\x00\x14" + encode_uid("WXYZ654321ZYXWV"),
                    relay,
                ),
                (b"\xf1\x84\x00\x14" + uid, relay),
            ]
        )
        route = Mock()
        route.getsockname.return_value = ("192.0.2.10", 41001)
        with (
            patch.object(CloudSession, "_new_socket", return_value=sock),
            patch("okam_bridge.vendor.cs2.socket.socket", return_value=route),
        ):
            # There is intentionally no IP in this config. A remote camera
            # must not depend on its private, possibly overlapping LAN address.
            session = connect_cloud(CONFIG, timeout=1)
        try:
            self.assertEqual(session._peer, relay)
            self.assertEqual(session.connect_path, "relay")
            self.assertEqual(session.counters.get("declined_readiness"), 1)
            self.assertTrue(session.prefer_relay)
        finally:
            session.close()
        self.assertTrue(sock.closed)

    def test_cancel_during_rendezvous_closes_socket(self):
        cancel = threading.Event()
        cancel.set()
        sock = RelaySocket()
        route = Mock()
        route.getsockname.return_value = ("192.0.2.10", 41001)
        with (
            patch.object(CloudSession, "_new_socket", return_value=sock),
            patch("okam_bridge.vendor.cs2.socket.socket", return_value=route),
        ):
            with self.assertRaisesRegex(CS2Error, "^cloud_connection_failed$"):
                connect_cloud(CONFIG, cancel=cancel)
        self.assertTrue(sock.closed)

    def test_cloud_failure_does_not_fall_back_to_local_camera(self):
        with (
            patch(
                "okam_bridge.transport.connect_cloud",
                side_effect=CS2Error("cloud_connection_failed"),
            ),
            patch("okam_bridge.transport.connect_lan") as lan,
        ):
            with self.assertRaises(CS2Error):
                connect_camera(dict(CONFIG, ip="192.0.2.55"))
        lan.assert_not_called()

    def test_legacy_configs_keep_lan_and_invalid_modes_are_rejected(self):
        config = dict(CONFIG)
        config.pop("connection_mode")
        with patch("okam_bridge.transport.connect_lan") as lan:
            self.assertIs(connect_camera(config), lan.return_value)
            lan.assert_called_once_with(config)
        with self.assertRaises(ValueError):
            connect_camera(dict(CONFIG, connection_mode="https"))

    def test_transport_status_has_no_peer_addresses_or_keys(self):
        camera = Camera(CONFIG, "ffmpeg")
        camera.session = Mock(connect_path="relay")
        self.assertEqual(
            camera.status()["transport"], {"mode": "cloud", "path": "relay"}
        )

    def test_independent_sd_session_uses_selected_transport(self):
        with (
            patch("okam_bridge.sd_archive.connect_camera") as connect,
            patch("okam_bridge.sd_archive.authenticate") as auth,
            patch("okam_bridge.sd_archive.authorize_account") as account,
        ):
            with SDSession(CONFIG):
                connect.assert_called_once_with(CONFIG)
                auth.assert_called_once_with(connect.return_value, CONFIG)
                account.assert_called_once_with(connect.return_value, CONFIG)
        connect.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
