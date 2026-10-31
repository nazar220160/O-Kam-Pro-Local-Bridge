import unittest
from okam_bridge.transport import LANSession


class SocketSink:
    def __init__(self):
        self.packets = []

    def sendto(self, data, address):
        self.packets.append(data)
        return len(data)


def packet(n):
    body = b"\xd1\x01" + n.to_bytes(2, "big") + bytes([n])
    return b"\xf1\xd0" + len(body).to_bytes(2, "big") + body


class RecoveryTests(unittest.TestCase):
    def test_dropped_out_of_order_packet_is_not_acknowledged(self):
        s = LANSession("ABCD123456ABCDE", "EBGDEOBOKGICGAIAFF:test-key")
        s._socket = SocketSink()
        s._peer = ("127.0.0.1", 32108)
        for n in range(1, 65):
            s._handle_data(packet(n))
        s._socket.packets.clear()
        s._handle_data(packet(65))
        self.assertEqual(
            s._socket.packets,
            [],
            "A dropped packet must remain eligible for retransmission",
        )
        s._handle_data(packet(0))
        s._handle_data(packet(65))
        self.assertEqual(bytes(s._channel_buffers[1]), bytes(range(66)))
