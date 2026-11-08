"""Adapt the upstream VP relay session to the bridge's camera interface."""

import struct
import threading
import time

from .metadata import camera_status_metadata
from .vendor.cs2 import (
    CS2Error,
    CS2Timeout,
    LOGIN_RESPONSE_COMMAND,
    MAX_COMMAND_BYTES,
    parse_result,
)
from .vendor.vp import (
    MAX_VIDEO_BYTES,
    VPError,
    decode_initialization,
    split_connection_input,
    video_lens,
)
from .vendor.vp_commands import make_cgi_request, parse_authentication
from .vendor.vp_session import VPSession, VPTimeout


class VPTransport(VPSession):
    """A CPPPP2 relay with bridge-compatible timeouts and command reads."""

    protocol = "vp"

    def __init__(self, identity, initialization, authentication, *, cancel=None):
        super().__init__(identity, initialization, cancel=cancel)
        self._auth = authentication
        self._close_lock = threading.Lock()
        self._stream_started = False
        self._control_buffer = bytearray()

    def request(self, path, *, timeout=5):
        try:
            payload = make_cgi_request(path, self._auth.user, self._auth.password)
        except VPError:
            raise CS2Error("vp_command_invalid") from None
        self.write(0, payload, timeout=timeout)

    def authenticate(self):
        from .transport import CameraAuthError

        self.request("get_status.cgi?name=admin&", timeout=20)
        deadline = time.monotonic() + 20
        while (remaining := deadline - time.monotonic()) > 0:
            reply = self.read_control(remaining)
            if reply is None:
                break
            command, payload = reply
            if command != LOGIN_RESPONSE_COMMAND:
                continue
            if parse_result(payload) != 0:
                raise CameraAuthError("camera_password_rejected")
            self.last_control_payload = payload
            self.camera_metadata = camera_status_metadata(payload)
            return self._auth.user, self._auth.password
        raise CameraAuthError("authentication_timeout")

    def authorize_account(self):
        self.request(
            "eye4_authentication.cgi?loginAccount="
            + self._auth.account
            + "&loginToken="
            + self._auth.token
            + "&"
        )
        self.request("check_user.cgi?")

    def start_video(self, substream):
        if type(substream) is not int or substream not in (0, 1, 2):
            raise ValueError("Invalid camera substream")
        # A lost write ACK does not prove the camera ignored the command.
        self._stream_started = True
        self.request(f"livestream.cgi?streamid=10&substream={substream}&")

    def read_lens_frame(self, timeout=10):
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            header = self.read_exact(1, 32, timeout=remaining)
            size = int.from_bytes(header[16:20], "little")
            if size == 0:
                continue
            lens = video_lens(header)
            if size > MAX_VIDEO_BYTES or lens > 15:
                raise CS2Error("camera video frame metadata is invalid")
            if header[4] in (0x10, 0x11):
                raise CS2Error("unsupported_video_codec")
            self.last_video_header = header
            return (
                self.read_exact(
                    1, size, timeout=max(0.001, deadline - time.monotonic())
                ),
                header[4],
                lens,
            )
        raise CS2Timeout("camera video frame timed out")

    def write(self, channel, payload, *, timeout=5):
        try:
            return super().write(channel, payload, timeout=timeout)
        except VPTimeout:
            raise CS2Timeout("camera channel write timed out") from None
        except VPError:
            raise CS2Error("vp_transport_failed") from None

    def read_exact(self, channel, count, *, timeout):
        prefix = b""
        if channel == 0 and self._control_buffer:
            prefix = bytes(self._control_buffer[:count])
            del self._control_buffer[: len(prefix)]
            if len(prefix) == count:
                return prefix
        try:
            return prefix + super().read_exact(
                channel, count - len(prefix), timeout=max(0.001, timeout)
            )
        except VPTimeout:
            if prefix:
                raise CS2Error("camera channel read interrupted") from None
            raise CS2Timeout("camera channel read timed out") from None
        except VPError:
            raise CS2Error("vp_transport_failed") from None

    def _count_kind(self, prefix, kind):
        key = prefix + kind
        if key in self.counters or len(self.counters) < 48:
            self.counters[key] += 1

    def read_control(self, timeout):
        """Read a complete control reply without discarding a partial one."""
        deadline = time.monotonic() + timeout
        buffer = self._control_buffer
        while True:
            buffer.extend(self._channels[0].read(MAX_COMMAND_BYTES + 8 - len(buffer)))
            if len(buffer) >= 8:
                magic, command, size, reserved = struct.unpack_from("<HHHH", buffer)
                if magic != 0x0A01 or reserved not in (0, 0x0100):
                    raise CS2Error("camera command framing is invalid")
                if len(buffer) >= 8 + size:
                    body = bytes(buffer[8 : 8 + size])
                    del buffer[: 8 + size]
                    self._count_kind("command_", f"{command:04x}")
                    return command, body
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                self._pump(min(0.2, remaining))
            except (VPError, OSError):
                raise CS2Error("vp_transport_failed") from None

    def close(self):
        with self._close_lock:
            if self._closed:
                return
            if self._stream_started:
                try:
                    self.request("livestream.cgi?streamid=16&substream=0&", timeout=0.5)
                except CS2Error:
                    pass
            super().close()
            self._control_buffer.clear()


def connect_vp(config, cancel=None):
    """Open a vendor relay selected by the VP directory."""
    if config.get("connection_mode") != "cloud":
        raise CS2Error("vp_requires_cloud")
    try:
        connection = split_connection_input(config.get("vp_connection"))
        initialization = decode_initialization(connection.initialization_record)
        account = config.get("account_id")
        token = config.get("account_token")
        if (
            not isinstance(account, str)
            or not account.isascii()
            or not account.isdigit()
        ):
            raise VPError("VP account identifier is invalid")
        if not isinstance(token, str) or not token:
            raise VPError("VP account token is unavailable")
        auth = parse_authentication(
            f"%%{config.get('username', 'admin')}&{account}&{token}",
            config.get("password"),
        )
        session = VPTransport(
            connection.transport_id, initialization, auth, cancel=cancel
        )
    except (VPError, UnicodeError):
        raise CS2Error("vp_configuration_invalid") from None
    try:
        session.connect(timeout=20, relay_only=True)
        if session.connect_path not in ("relay", "relay-tcp"):
            raise VPError("VP relay connection is unavailable")
        return session
    except (VPError, OSError):
        session.close()
        raise CS2Error("cloud_connection_failed") from None
