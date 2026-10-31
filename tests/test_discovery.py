import socket, threading, unittest
from okam_bridge.transport import discover_lan
from okam_bridge.vendor.cs2 import encrypt_packet, encode_uid


class DiscoveryTests(unittest.TestCase):
    def test_finds_only_uid_visible_to_requested_account_record(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        s.settimeout(2)
        port = s.getsockname()[1]

        def peer():
            try:
                _, addr = s.recvfrom(4096)
                for uid in ("WXYZ654321ZYXWV", "ABCD123456ABCDE"):
                    s.sendto(
                        encrypt_packet(
                            "test-key", b"\xf1\x41\x00\x14" + encode_uid(uid)
                        ),
                        addr,
                    )
            finally:
                s.close()

        t = threading.Thread(target=peer)
        t.start()
        result = discover_lan(
            "ABCD123456ABCDE",
            "EBGDEOBOKGICGAIAFF:test-key",
            timeout=1,
            targets=["127.0.0.1"],
            ports=[port],
        )
        self.assertEqual(result, {"ip": "127.0.0.1", "port": port})
        t.join()
