import socket
import struct
import tempfile
from pathlib import Path
import unittest
from okam_bridge.capture import credentials_from_capture
from okam_bridge.vendor.cs2 import encrypt_packet, make_cgi_request


class CaptureTests(unittest.TestCase):
    def test_import_targets_only_selected_camera(self):
        clear = (
            b"\xf1\xd0"
            + (
                4 + len(make_cgi_request("get_status.cgi?", "admin", "example-secret"))
            ).to_bytes(2, "big")
            + b"\xd1\x00\x00\x00"
            + make_cgi_request("get_status.cgi?", "admin", "example-secret")
        )
        data = encrypt_packet("test-key", clear)
        udp = struct.pack(">HHHH", 12345, 32108, 8 + len(data), 0) + data
        ip = (
            b"\x45\x00"
            + (20 + len(udp)).to_bytes(2, "big")
            + b"\x00" * 5
            + b"\x11"
            + b"\x00\x00"
            + socket.inet_aton("192.168.20.13")
            + socket.inet_aton("192.168.20.12")
        )
        frame = b"\x00" * 12 + b"\x08\x00" + ip + udp
        pcap = (
            struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
            + struct.pack("<IIII", 0, 0, len(frame), len(frame))
            + frame
        )
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "input.pcap"
            p.write_bytes(pcap)
            result = credentials_from_capture(p, "192.168.20.12", "test-key")
            self.assertEqual(
                result,
                {
                    "username": "admin",
                    "password": "example-secret",
                    "compatibility_password": "888888",
                },
            )
            with self.assertRaises(ValueError):
                credentials_from_capture(p, "192.168.1.105", "test-key")

    def test_wrong_format_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "input"
            p.write_bytes(b"not a capture")
            with self.assertRaises(ValueError):
                credentials_from_capture(p, "192.168.20.12", "test-key")
