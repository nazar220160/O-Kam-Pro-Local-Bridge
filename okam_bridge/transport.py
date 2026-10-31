"""Encrypted CS2/PPPP sessions over LAN or the vendor's cloud relay."""

import socket
import time
import struct
import re
from urllib.parse import quote
from .vendor.cs2 import (
    CS2Session,
    CS2Error,
    encrypt_packet,
    decrypt_packet,
    write_command,
    make_cgi_request,
    read_command_result,
    LOGIN_RESPONSE_COMMAND,
    LIVE_STREAM_RESPONSE_COMMANDS,
)


class LANSession(CS2Session):
    def _handle_data(self, packet):
        body = packet[4:]
        if (
            len(packet) >= 8
            and len(body) == int.from_bytes(packet[2:4], "big")
            and body[0] == 0xD1
            and body[1] < 8
        ):
            channel = body[1]
            sequence = int.from_bytes(body[2:4], "big")
            distance = (sequence - self._incoming_sequence[channel]) & 0xFFFF
            waiting = self._out_of_order[channel]
            if 0 < distance < 0x8000 and sequence not in waiting and len(waiting) >= 64:
                # Upstream ACKs before checking buffer capacity. An ACK for a
                # discarded future packet prevents retransmission and leaves
                # the shared video channel permanently missing those bytes.
                self._count("data_packets_deferred")
                return
        super()._handle_data(packet)


class CloudSession(LANSession):
    """Vendor relay negotiation with the same reliable media handling as LAN.

    Cancellation also applies during the 55-second rendezvous and subsequent
    authentication reads, before Camera can publish the connected session.
    """

    def __init__(self, *args, cancel=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cancel = cancel

    def _receive_clear(self):
        if self.cancel is not None and self.cancel.is_set():
            raise CS2Error("camera_stop_requested")
        return super()._receive_clear()


class CameraAuthError(CS2Error):
    pass


class CameraStartError(CS2Error):
    pass


def connect_lan(camera, timeout=6.0):
    session = LANSession(
        camera["transport_uid"], camera["service_parameter"], prefer_relay=False
    )
    session._socket = session._new_socket()
    session._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    host = camera["ip"]
    ports = camera.get("ports", [32108, 32100])
    targets = {host, camera.get("broadcast", "255.255.255.255")}
    deadline = time.monotonic() + timeout
    last_send = 0
    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now - last_send >= 1:
                for target in targets:
                    for port in ports:
                        for packet in (b"\xf1\x30\x00\x00",):
                            # This camera requires encrypted LAN search even
                            # though upstream sends F1 30 as clear by default.
                            try:
                                session._socket.sendto(
                                    encrypt_packet(session.key, packet), (target, port)
                                )
                            except OSError:
                                pass  # One unavailable broadcast interface must not abort unicast discovery.
                last_send = now
            received = session._receive_clear()
            if received is None:
                continue
            packet, address = received
            if address[0] != host or len(packet) != 24 or packet[4:] != session.uid:
                continue
            if packet[:2] == b"\xf1\x41":
                # Discovery announces a per-session port. Echo the punch to
                # that port and wait for the camera's readiness, rather than
                # accepting the discovery announcement as a ready session.
                session._socket.sendto(
                    encrypt_packet(session.key, b"\xf1\x41\x00\x14" + session.uid),
                    address,
                )
                continue
            if packet[:2] != b"\xf1\x42":
                continue
            session._peer = address
            session.connect_path = "LAN"
            session._send_clear(b"\xf1\xe0\x00\x00", address)
            return session
        raise CS2Error("no_lan_reply")
    except BaseException:
        session.close()
        raise


def connect_cloud(camera, timeout=55.0, cancel=None):
    """Find a relay by camera UID; a camera's LAN IP is never a relay address."""
    session = CloudSession(
        camera["transport_uid"],
        camera["service_parameter"],
        prefer_relay=True,
        cancel=cancel,
    )
    try:
        session.connect(timeout=timeout)
        # Keep the explicit cloud button honest: never silently use LAN or a
        # directly punched camera peer when the user requested a vendor relay.
        if session.connect_path != "relay":
            raise CS2Error("cloud_connection_failed")
        return session
    except (CS2Error, OSError):
        session.close()
        raise CS2Error("cloud_connection_failed") from None
    except BaseException:
        session.close()
        raise


def connect_camera(camera, cancel=None):
    mode = camera.get("connection_mode", "lan")
    if mode == "lan":
        return connect_lan(camera)
    if mode == "cloud":
        return connect_cloud(camera, cancel=cancel)
    raise ValueError("Invalid camera connection mode")


def make_request(path, user, password, compatibility_password=None, account_id=None):
    if any(len(v) > 512 or any(ord(c) < 32 for c in v) for v in (user, password)):
        raise ValueError("Invalid camera credentials")
    if account_id is not None:
        if (
            not isinstance(account_id, str)
            or not account_id.isascii()
            or not account_id.isdigit()
        ):
            raise ValueError("Invalid account identifier")
        path += "userId=" + account_id + "&"
    legacy_password = (
        password if compatibility_password is None else compatibility_password
    )
    user, password, legacy_password = (
        quote(v, safe="") for v in (user, password, legacy_password)
    )
    data = (
        f"GET /{path}loginuse={user}&loginpas={password}&user={user}&pwd={legacy_password}&"
    ).encode("ascii")
    return struct.pack("<HHHH", 0x0A01, 0, len(data), 0) + data


def response_result(payload):
    values = [
        int(v)
        for v in re.findall(rb'(?<![A-Za-z_])result\s*=\s*["\']?(-?[0-9]+)', payload)
    ]
    return next((v for v in values if v < 0), values[-1] if values else None)


def read_reply(session, commands, timeout=10):
    from .vendor.cs2 import read_command, CS2Timeout

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            command, data = read_command(session, timeout=end - time.monotonic())
        except CS2Timeout:
            return None
        session.last_control_payload = data
        result = response_result(data)
        if result is not None and (command in commands or result < 0):
            return command, result
    return None


def authenticate(session, camera):
    user = camera.get("username", "admin")
    password = camera["password"]
    write_command(
        session,
        make_request(
            "get_status.cgi?name=admin&",
            user,
            password,
            camera.get("compatibility_password"),
            account_id=camera.get("account_id"),
        ),
    )
    result = read_reply(session, (LOGIN_RESPONSE_COMMAND,), timeout=10)
    if not result or result[1] != 0:
        raise CameraAuthError(
            "camera_password_rejected" if result else "authentication_timeout"
        )
    from .metadata import camera_status_metadata

    session.camera_metadata = camera_status_metadata(
        getattr(session, "last_control_payload", b"")
    )
    return user, password


def authorize_account(session, camera):
    """Firmware requiring account-token validation before live video."""
    token = camera.get("account_token")
    if not token:
        return
    account = camera.get("account_id")
    if not isinstance(account, str) or not account.isascii() or not account.isdigit():
        raise ValueError("Invalid account identifier")
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= 512
        or any(ord(c) < 33 or ord(c) > 126 for c in token)
    ):
        raise ValueError("Invalid account token")
    for path in (
        "eye4_authentication.cgi?loginAccount="
        + account
        + "&loginToken="
        + quote(token, safe="")
        + "&",
        "check_user.cgi?",
    ):
        write_command(
            session,
            make_request(
                path,
                camera.get("username", "admin"),
                camera["password"],
                camera.get("compatibility_password"),
                account_id=account,
            ),
        )


def set_video_quality(session, camera, quality):
    """Observed O-Kam Pro live-quality control, independent of substream."""
    values = {"high": 1, "medium": 2, "low": 4}
    if not isinstance(quality, str) or quality not in values:
        raise ValueError("Invalid video quality")
    write_command(
        session,
        make_request(
            f"camera_control.cgi?param=16&value={values[quality]}&",
            camera.get("username", "admin"),
            camera["password"],
            camera.get("compatibility_password"),
            account_id=camera.get("account_id"),
        ),
    )


def start_video(
    session, user, password, substream=1, compatibility_password=None, account_id=None
):
    write_command(
        session,
        make_request(
            f"livestream.cgi?streamid=10&substream={substream}&",
            user,
            password,
            compatibility_password,
            account_id=account_id,
        ),
    )
    response = read_reply(session, LIVE_STREAM_RESPONSE_COMMANDS, timeout=5)
    if response and response[1] != 0:
        raise CameraStartError("video_start_rejected:" + str(response[1]))


def start_audio(session, user, password, compatibility_password=None, account_id=None):
    """Receive live G.711 A-law audio (VSDK stream 7), without microphone writes."""
    write_command(
        session,
        make_request(
            "audiostream.cgi?streamid=7&",
            user,
            password,
            compatibility_password,
            account_id=account_id,
        ),
    )
    response = read_reply(session, (0x6031,), timeout=3)
    if response is None or response[1] != 0:
        raise CS2Error("camera_audio_unavailable")


def read_lens_frame(session, timeout=10):
    from .vendor.cs2 import MAX_FRAME_BYTES

    header = session.read_exact(1, 32, timeout=timeout)
    if len(header) != 32 or header[:4] != b"\x55\xaa\x15\xa8":
        raise CS2Error("camera video framing is invalid")
    size = int.from_bytes(header[16:20], "little")
    lens = int.from_bytes(header[26:28], "little")
    if not 0 < size <= MAX_FRAME_BYTES or lens > 15:
        raise CS2Error("camera video frame metadata is invalid")
    session.last_video_header = header
    return session.read_exact(1, size, timeout=timeout), header[4], lens


def discover_lan(uid, service_parameter, timeout=6, targets=None, ports=None):
    import ipaddress

    session = LANSession(uid, service_parameter, prefer_relay=False)
    sock = session._new_socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    destinations = targets or ["255.255.255.255"]
    ports = ports or [32108, 32100]
    end = time.monotonic() + timeout
    last = 0
    try:
        while time.monotonic() < end:
            if time.monotonic() - last >= 1:
                for host in destinations:
                    for port in ports:
                        try:
                            sock.sendto(
                                encrypt_packet(session.key, b"\xf1\x30\x00\x00"),
                                (host, port),
                            )
                        except OSError:
                            pass
                last = time.monotonic()
            try:
                wire, address = sock.recvfrom(65535)
            except (socket.timeout, TimeoutError, ConnectionResetError):
                continue
            data = wire if wire[:1] == b"\xf1" else decrypt_packet(session.key, wire)
            if (
                len(data) < 24
                or data[:2] not in (b"\xf1\x41", b"\xf1\x42", b"\xf1\x43")
                or data[4:24] != session.uid
            ):
                continue
            ip = ipaddress.IPv4Address(address[0])
            if ip.is_private and not ip.is_unspecified and not ip.is_multicast:
                return {"ip": str(ip), "port": address[1]}
        raise CS2Error("no_lan_reply")
    finally:
        sock.close()
