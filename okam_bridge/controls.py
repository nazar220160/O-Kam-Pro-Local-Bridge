"""Bounded native camera controls and data projection; never evaluate CGI JS."""

import json
import re
import struct
import threading
import time
from urllib.parse import parse_qsl, urlencode, quote
from .transport import make_request, response_result
from .vendor.cs2 import CS2Error


class ControlError(ValueError):
    pass


READS = {
    "status": ("get_status.cgi?name=admin&", 0x6001),
    "parameters": ("get_params.cgi?", 0x6002),
    "video": ("get_camera_params.cgi?", 0x6003),
    "tracking": ("trans_cmd_string.cgi?cmd=2127&command=1&", None),
    "zoom_tracking": ("trans_cmd_string.cgi?cmd=2126&command=1&", None),
    "light": ("trans_cmd_string.cgi?cmd=2109&command=2&", None),
    "indicator": ("trans_cmd_string.cgi?cmd=2125&command=1&", None),
    "presets": ("trans_cmd_string.cgi?cmd=2161&command=0&", None),
    "archive_dates": ("get_record_file.cgi?GetType=date&", None),
    "recording": ("get_record.cgi?", None),
    "sleep": ("trans_cmd_string.cgi?cmd=2106&command=17&", None),
    "power": ("trans_cmd_string.cgi?cmd=2106&command=14&", None),
}
# Feature flags advertise the camera, not proof of every driver operation.
FEATURES = {
    "ptz": ("haveMotor", "support_ptz", "PTZEnable"),
    "microphone": ("haveMic",),
    "speaker": ("haveHorn",),
    "zoom": ("MaxZoomMultiple", "support_zoom", "support_focus"),
    "tracking": (
        "support_humanoid_tracking",
        "supportHumanoidTracking",
        "support_humanoid",
        "support_humanDetect",
        "track_status",
    ),
    "sd_card": (
        "sd_status",
        "sdstatus",
        "sdcard_status",
        "sdtotal",
        "sd_total",
        "sdsize",
    ),
    "white_light": (
        "haveWhiteLight",
        "support_white_light",
        "support_manual_light",
        "support_full_color_night_vision_mode",
    ),
    "night_vision": ("support_full_color_night_vision_mode", "night_vision_mode"),
    "presets": ("support_preset_auto", "support_ptz_guard"),
    "ai": ("support_AI",),
    "onvif": ("onvif_support_enable",),
}
SECRET_KEY = re.compile(
    r"pass|pwd|token|security|secret|credential|auth|wifi.*key|^key\d*$|^user\d*_(?:name|user)|email",
    re.I,
)


def public_fields(value, secrets=(), depth=0):
    if depth > 6:
        return "[depth limit]"
    if isinstance(value, dict):
        return {
            str(k)[:120]: public_fields(v, secrets, depth + 1)
            for k, v in list(value.items())[:1500]
            if not SECRET_KEY.search(str(k))
        }
    if isinstance(value, (list, tuple)):
        return [public_fields(v, secrets, depth + 1) for v in value[:1000]]
    if isinstance(value, str):
        for secret in secrets:
            if isinstance(secret, str) and len(secret) >= 4:
                value = value.replace(secret, "[hidden]")
        return value[:8192]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:8192]


def redact_response(value, secrets=()):
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= 4:
            value = value.replace(secret, "[hidden]")
    value = re.sub(
        r'(?i)((?:["\x27]?)(?:[A-Za-z_0-9]*(?:password|loginpas|pwd|token|security|secret|wifi_key)[A-Za-z_0-9]*)(?:["\x27]?)\s*[=:]\s*)(?:"(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27|[^;&\r\n ]+)',
        r"\1[hidden]",
        value,
    )
    return value[:65536]


def parse_variables(payload):
    if isinstance(payload, bytes):
        payload = payload[: 1024 * 1024].decode("utf-8", errors="replace")
    if payload.lstrip().startswith(("{", "[")):
        try:
            value = json.loads(payload)
            if isinstance(value, dict):
                return dict(list(value.items())[:1500])
            if isinstance(value, list):
                return {"items": value[:1000]}
        except (ValueError, RecursionError):
            pass
    pattern = r'\bvar\s+([A-Za-z_][A-Za-z_0-9]*)\s*=\s*("(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27|[^;\r\n]*)(?:;|$)'
    result = {}

    def scalar(value):
        value = value.strip()[:8192]
        if value in ("new Array()", "new Array(0)"):
            return []
        try:
            return json.loads(value)
        except (ValueError, TypeError, RecursionError):
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                return value[1:-1]
            return value

    for match in re.finditer(pattern, payload):
        if len(result) >= 1500:
            break
        result[match[1]] = scalar(match[2])
    indexed = r'\b([A-Za-z_][A-Za-z_0-9]*)\[(\d{1,3})\]\s*=\s*("(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27|[^;\r\n]*)(?:;|$)'
    for match in re.finditer(indexed, payload):
        key = match[1]
        index = int(match[2])
        if key not in result:
            continue
        if isinstance(result[key], list):
            while len(result[key]) <= index:
                result[key].append(None)
            result[key][index] = scalar(match[3])
    return result


def capabilities(groups):
    values = {
        k: v
        for group in groups.values()
        if isinstance(group, dict)
        for k, v in group.items()
    }
    out = {}
    for name, keys in FEATURES.items():
        found = [(key, values[key]) for key in keys if key in values]
        out[name] = {
            "available": (
                any(
                    str(v).lower() not in ("0", "false", "none", "null", "", "-1")
                    for _, v in found
                )
                if found
                else None
            ),
            "evidence": dict(found),
        }
    return out


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ControlError("invalid_control_value")
    return value


def native_path(path):
    if (
        not isinstance(path, str)
        or not 1 <= len(path) <= 4096
        or any(ord(c) < 32 or ord(c) > 126 for c in path)
    ):
        raise ControlError("invalid_native_command")
    path = path.lstrip("/")
    name, sep, query = path.partition("?")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*\.cgi", name):
        raise ControlError("invalid_native_command")
    try:
        items = parse_qsl(query, keep_blank_values=True, max_num_fields=100)
    except ValueError:
        raise ControlError("invalid_native_command") from None
    for key, value in items:
        if key.lower() in (
            "loginuse",
            "loginpas",
            "user",
            "pwd",
            "userid",
            "loginaccount",
            "logintoken",
        ) or any(ord(c) < 32 or ord(c) > 126 for c in key + value):
            raise ControlError("invalid_native_command")
    return name + "?" + (urlencode(items) + "&" if items else "")


def build_action(action, args=None):
    if not isinstance(action, str) or not isinstance(args or {}, dict):
        raise ControlError("invalid_control_value")
    a = args or {}
    expected = None
    duration = 0
    stop = None
    if action == "query":
        key = a.get("section", "status")
        if not isinstance(key, str) or key not in READS:
            raise ControlError("invalid_control_value")
        path, expected = READS[key]
    elif action == "ptz":
        direction = a.get("direction")
        codes = {"up": 0, "down": 2, "left": 4, "right": 6}
        if not isinstance(direction, str) or direction not in codes:
            raise ControlError("invalid_control_value")
        speed = integer(a.get("speed", 1), 1, 10)
        lens = integer(a.get("lens", 0), 0, 15)
        duration = integer(a.get("duration_ms", 200), 80, 600) / 1000
        code = codes[direction]
        path = f"decoder_control.cgi?command={code}&onestep=0&curr_binocular={lens}&motor_speed={speed}&"
        stop = f"decoder_control.cgi?command={code+1}&onestep=0&"
    elif action == "ptz_step":
        codes = {"up": 0, "down": 2, "left": 4, "right": 6}
        direction = a.get("direction")
        if not isinstance(direction, str) or direction not in codes:
            raise ControlError("invalid_control_value")
        path = f"decoder_control.cgi?command={codes[direction]}&onestep=1&"
        expected = 0x6019
    elif action == "ptz_stop":
        path = "decoder_control.cgi?command=1&onestep=0&"
    elif action == "calibrate":
        path = "decoder_control.cgi?command=25&onestep=0&"
    elif action == "cruise":
        mode = a.get("mode")
        codes = {
            "horizontal": 28,
            "vertical": 26,
            "presets": 22,
            "stop_horizontal": 29,
            "stop_vertical": 27,
            "stop_presets": 23,
        }
        if not isinstance(mode, str) or mode not in codes:
            raise ControlError("invalid_control_value")
        path = f"decoder_control.cgi?command={codes[mode]}&onestep=0&"
    elif action == "preset":
        slot = integer(a.get("slot"), 1, 5) - 1
        operation = a.get("operation")
        codes = {"save": 30 + 2 * slot, "goto": 31 + 2 * slot, "delete": 62 + slot}
        if not isinstance(operation, str) or operation not in codes:
            raise ControlError("invalid_control_value")
        path = f"decoder_control.cgi?command={codes[operation]}&onestep=0&"
        expected = 0x6019
    elif action == "guard":
        path = (
            f'set_sensor_preset.cgi?sensorid=255&presetid={integer(a.get("slot"),0,5)}&'
        )
    elif action == "volume":
        channel = a.get("channel")
        value = integer(a.get("value"), 0, 31)
        if channel not in ("microphone", "speaker"):
            raise ControlError("invalid_control_value")
        param = 24 if channel == "microphone" else 25
        path = f"camera_control.cgi?param={param}&value={value}&"
        expected = 0x6012
    elif action == "quality":
        quality = a.get("quality")
        values = {"high": 1, "medium": 2, "low": 4}
        if not isinstance(quality, str) or quality not in values:
            raise ControlError("invalid_quality")
        path = f"camera_control.cgi?param=16&value={values[quality]}&"
        expected = 0x6012
    elif action == "image":
        field = a.get("field")
        spec = {
            "brightness": (1, 0, 255),
            "contrast": (2, 0, 255),
            "orientation": (5, 0, 3),
            "night": (33, 0, 2),
        }
        if not isinstance(field, str) or field not in spec:
            raise ControlError("invalid_control_value")
        param, low, high = spec[field]
        value = integer(a.get("value"), low, high)
        path = f"camera_control.cgi?param={param}&value={value}&"
        expected = 0x6012
    elif action == "zoom":
        path = f'decoder_control.cgi?command=84&param={integer(a.get("scale"),1,30)}&'
    elif action in ("light", "siren", "tracking", "zoom_tracking", "indicator"):
        value = integer(a.get("value"), 0, 1)
        template = {
            "light": "trans_cmd_string.cgi?cmd=2109&command=0&light={}&",
            "siren": "trans_cmd_string.cgi?cmd=2109&command=0&siren={}&",
            "tracking": "trans_cmd_string.cgi?cmd=2127&command=0&enable={}&",
            "zoom_tracking": "trans_cmd_string.cgi?cmd=2126&command=0&humanoid_zoom={}&",
            "indicator": "trans_cmd_string.cgi?cmd=2125&command=0&hide_led_disable={}&",
        }
        path = template[action].format(value)
    elif action == "osd":
        path = f'set_misc.cgi?osdenable={integer(a.get("value"),0,1)}&'
    elif action == "record_audio":
        path = f'set_recordsch.cgi?record_audio={integer(a.get("value"),0,1)}&'
    elif action == "camera_parameter":
        # Explicit expert numeric parameter. Labels are model-specific.
        param = integer(a.get("param"), 0, 255)
        value = integer(a.get("value"), -10000, 10000)
        path = f"camera_control.cgi?param={param}&value={value}&"
    elif action == "archive_files":
        date = a.get("date")
        if not isinstance(date, str) or not re.fullmatch(r"[0-9_-]{8,16}", date):
            raise ControlError("invalid_control_value")
        path = "get_record_file.cgi?GetType=file&dirname=" + date + "&"
    elif action == "plaintext_password":
        enabled = a.get("enabled")
        if type(enabled) is not bool:
            raise ControlError("invalid_control_value")
        suffix = ""
        if enabled:
            password = a.get("password")
            if (
                not isinstance(password, str)
                or not 8 <= len(password) <= 63
                or any(ord(c) < 33 or ord(c) > 126 for c in password)
            ):
                raise ControlError("invalid_control_value")
            suffix = "ExPwd=" + quote(password, safe="") + "&"
        path = (
            "set_users.cgi?pwd_change_realtime=1&ExUser=admin&"
            + suffix
            + "ExUserSwitch="
            + str(int(enabled))
            + "&"
        )
        expected = 0x600E
    elif action == "native":
        path = native_path(a.get("path"))
    else:
        raise ControlError("unknown_control")
    if expected is None:
        name = path.split("?", 1)[0]
        expected = {
            "camera_control.cgi": 0x6012,
            "decoder_control.cgi": 0x6019,
            "get_status.cgi": 0x6001,
            "get_camera_params.cgi": 0x6003,
            "get_params.cgi": 0x6002,
            "trans_cmd_string.cgi": 0x60D1,
            "get_record_file.cgi": 0x6007,
        }.get(name)
    after_path = (
        "camera_control.cgi?param=14&value=1&"
        if action == "image" and a.get("field") == "night"
        else None
    )
    return {
        "action": action,
        "path": path,
        "expected": expected,
        "duration": duration,
        "stop": stop,
        "args": a,
        "after_path": after_path,
    }


class ControlJob:
    def __init__(self, action, ttl=8):
        self.action = action
        self.deadline = time.monotonic() + ttl
        self.done = threading.Event()
        self.result = None
        self.error = None
        self.lock = threading.Lock()
        self.started = False
        self.cancelled = False

    def claim(self):
        with self.lock:
            if self.cancelled or time.monotonic() > self.deadline:
                self.error = "control_expired"
                self.done.set()
                return False
            self.started = True
            return True

    def cancel(self):
        with self.lock:
            if not self.started:
                self.cancelled = True


def read_control(session, timeout):
    """Peek whole channel-0 messages; a partial reply survives a timeout."""
    deadline = time.monotonic() + timeout
    while True:
        buffer = session._channel_buffers[0]
        if len(buffer) >= 8:
            magic, command, size, _ = struct.unpack_from("<HHHH", buffer)
            if magic != 0x0A01 or size > 1024 * 1024:
                raise CS2Error("camera command framing is invalid")
            if len(buffer) >= 8 + size:
                body = bytes(buffer[8 : 8 + size])
                del buffer[: 8 + size]
                return command, body
        if time.monotonic() >= deadline:
            return None
        session._pump()


def _send(session, config, path, timeout=1):
    request = make_request(
        path,
        config.get("username", "admin"),
        config["password"],
        config.get("compatibility_password"),
        account_id=config.get("account_id"),
    )
    session.write(0, request, timeout=timeout)


def _execute_single(session, config, action, stop_event=None):
    if stop_event is not None and stop_event.is_set():
        return {"state": "interrupted", "transport_acknowledged": False}
    secrets = (
        config.get("password"),
        config.get("account_token"),
        action.get("args", {}).get("password"),
    )
    if action["action"] == "ptz":
        try:
            _send(session, config, action["path"], timeout=0.6)
            if stop_event:
                stop_event.wait(action["duration"])
            else:
                time.sleep(action["duration"])
        finally:
            _send(session, config, action["stop"], timeout=0.6)
        return {
            "state": "sent",
            "transport_acknowledged": True,
            "message": "PTZ pulse and stop sent",
        }
    if action["action"] == "ptz_stop":
        for n in (1, 3, 5, 7):
            _send(
                session,
                config,
                f"decoder_control.cgi?command={n}&onestep=0&",
                timeout=0.4,
            )
        return {"state": "sent", "transport_acknowledged": True}
    # Discard completed old replies before attributing a new one. Partial
    # messages remain intact until completed, never consumed speculatively.
    for _ in range(64):
        if read_control(session, 0) is None:
            break
    _send(session, config, action["path"])
    deadline = time.monotonic() + 2
    reply = None
    while time.monotonic() < deadline:
        candidate = read_control(session, deadline - time.monotonic())
        if candidate is None:
            break
        if action["expected"] is not None and candidate[0] != action["expected"]:
            continue
        reply = candidate
        break
    if reply is None:
        return {
            "state": "sent",
            "transport_acknowledged": True,
            "response": None,
            "parameters": {},
        }
    command, payload = reply
    result = response_result(payload)
    if action.get("verify_credentials"):
        values = parse_variables(payload)
        return {
            "external_access_enabled": (
                None
                if "ExUserSwitch" not in values
                else str(values["ExUserSwitch"]) == "1"
            ),
            "web_password_configured": (
                None if "WebPwd" not in values else bool(values["WebPwd"])
            ),
        }
    return {
        "state": (
            "rejected"
            if result is not None and result < 0
            else "confirmed" if result == 0 else "response"
        ),
        "transport_acknowledged": True,
        "result": result,
        "response_command": command,
        "parameters": public_fields(parse_variables(payload), secrets),
        "response": redact_response(payload.decode("utf-8", errors="replace"), secrets),
    }


def execute_action(session, config, action, stop_event=None):
    result = _execute_single(session, config, action, stop_event)
    if action["action"] == "plaintext_password" and result["state"] == "confirmed":
        checks = {}
        for path, code in (("get_status.cgi?", 0x6001), ("get_params.cgi?", 0x6002)):
            if stop_event is not None and stop_event.is_set():
                break
            check = dict(action, path=path, expected=code, verify_credentials=True)
            response = _execute_single(session, config, check, stop_event)
            checks.update(
                {
                    k: v
                    for k, v in response.items()
                    if k in ("external_access_enabled", "web_password_configured")
                    and v is not None
                }
            )
        result["verification"] = checks
        result["protocol_verified"] = False
    if action.get("after_path") and result["state"] not in ("rejected", "interrupted"):
        if stop_event is not None and stop_event.is_set():
            return {
                "state": "interrupted",
                "transport_acknowledged": result.get("transport_acknowledged", False),
                "steps": [result],
            }
        following = dict(action, path=action["after_path"], after_path=None)
        second = _execute_single(session, config, following, stop_event)
        state = (
            "interrupted"
            if second["state"] == "interrupted"
            else (
                "rejected"
                if second["state"] == "rejected"
                else (
                    "confirmed"
                    if result["state"] == second["state"] == "confirmed"
                    else "sent"
                )
            )
        )
        return {
            "state": state,
            "transport_acknowledged": True,
            "result": second.get("result"),
            "steps": [result, second],
        }
    return result
