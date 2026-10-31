import socket
import threading
import time
import unittest
from okam_bridge.transport import connect_lan
from okam_bridge.vendor.cs2 import encode_uid, encrypt_packet, decrypt_packet


class HandshakeTests(unittest.TestCase):
    def test_client_echoes_punch_and_waits_for_camera_ready(self):
        key = "test-key"
        uid = encode_uid("ABCD123456ABCDE")
        authorized = threading.Event()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(1)
        port = sock.getsockname()[1]
        child = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        child.bind(("127.0.0.1", 0))
        child.settimeout(1)

        def peer():
            try:
                packet, addr = sock.recvfrom(4096)
                child.sendto(encrypt_packet(key, b"\xf1\x41\x00\x14" + uid), addr)
                end = time.monotonic() + 1
                while time.monotonic() < end:
                    packet, addr = child.recvfrom(4096)
                    if decrypt_packet(key, packet) == b"\xf1\x41\x00\x14" + uid:
                        authorized.set()
                        child.sendto(
                            encrypt_packet(key, b"\xf1\x42\x00\x14" + uid), addr
                        )
                        return
            except socket.timeout:
                pass
            finally:
                sock.close()
                child.close()

        t = threading.Thread(target=peer)
        t.start()
        s = connect_lan(
            {
                "ip": "127.0.0.1",
                "transport_uid": "ABCD123456ABCDE",
                "service_parameter": "EBGDEOBOKGICGAIAFF:test-key",
                "ports": [port],
            },
            timeout=1,
        )
        try:
            self.assertTrue(
                authorized.wait(0.5),
                "Client accepted discovery as readiness without echoing the punch",
            )
        finally:
            s.close()
            t.join()
