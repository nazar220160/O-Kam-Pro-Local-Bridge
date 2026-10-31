"""Optional one-time import from the owner's local app traffic.

No packet capture is performed here; a user supplies a classic PCAP file.
Only outbound CGI credentials addressed to the selected camera are read.
"""

from pathlib import Path
import re
import socket
import struct
from urllib.parse import parse_qs
from .vendor.cs2 import decrypt_packet


def credentials_from_capture(path, camera_ip, key):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Capture must be at most 64 MiB")
    data = path.read_bytes()
    if len(data) < 24:
        raise ValueError("Not a classic PCAP capture")
    if data[:4] in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        endian = "<"
    elif data[:4] in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = ">"
    else:
        raise ValueError("Export a classic PCAP file, not PCAPNG")
    link = struct.unpack_from(endian + "I", data, 20)[0]
    if link not in (1, 113):
        raise ValueError("PCAP must use Ethernet or Linux cooked capture")
    offset = 24
    found = None
    while offset + 16 <= len(data):
        size = struct.unpack_from(endian + "I", data, offset + 8)[0]
        offset += 16
        if size > 1024 * 1024 or offset + size > len(data):
            raise ValueError("Truncated or oversized PCAP packet")
        packet = data[offset : offset + size]
        offset += size
        ip = 14 if link == 1 else 16
        if link == 1 and packet[12:14] != b"\x08\x00":
            continue
        if len(packet) < ip + 28 or packet[ip] >> 4 != 4 or packet[ip + 9] != 17:
            continue
        if socket.inet_ntoa(packet[ip + 16 : ip + 20]) != camera_ip:
            continue
        udp = ip + (packet[ip] & 15) * 4
        if len(packet) < udp + 8:
            continue
        length = struct.unpack_from(">H", packet, udp + 4)[0]
        if length < 8:
            continue
        clear = decrypt_packet(key, packet[udp + 8 : udp + length])
        if clear[:2] != b"\xf1\xd0" or len(clear) < 8 or clear[5] != 0:
            continue
        # CGI requests are small and normally fit one DRW packet. Fragmented
        # requests are ignored rather than importing an incomplete credential.
        for match in re.finditer(rb"GET /[A-Za-z_]+\.cgi\?([^\x00\r\n ]+)", clear[8:]):
            query = parse_qs(match[1].decode("ascii", errors="ignore"))
            if query.get("loginuse") and query.get("loginpas"):
                found = {
                    "username": query["loginuse"][0],
                    "password": query["loginpas"][0],
                    "compatibility_password": query.get("pwd", ["888888"])[0],
                }
    if found is None:
        raise ValueError("No matching camera credentials found in capture")
    return found
