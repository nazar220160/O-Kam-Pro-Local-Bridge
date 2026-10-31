"""ONVIF PTZ facade for bridge exports, using only confirmed native operations.

The facade has velocity control and five native preset slots. It deliberately
omits position spaces and position status: the native control transport cannot
measure absolute position. Camera ONVIF settings are never accessed here.
Schema: https://www.onvif.org/ver20/ptz/wsdl/ptz.wsdl
"""

import math
import re
from datetime import datetime, timezone

from .onvif import NS, node

PAN_TILT_VELOCITY = "http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"
DEFAULT_TIMEOUT = 0.6
MIN_TIMEOUT = 0.08
MAX_TIMEOUT = 5.0


def _text(request, name, required=True):
    values = request.findall("tptz:" + name, NS)
    if len(values) > 1 or (required and (not values or not values[0].text)):
        raise ValueError("Missing or duplicate PTZ parameter")
    return (values[0].text or "") if values else None


def _profile(item, token):
    profile = next((p for p in item["profiles"] if p["token"] == token), None)
    if profile is None:
        raise ValueError("Unknown PTZ profile")
    return profile


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid PTZ velocity") from exc
    if not math.isfinite(number) or not -1 <= number <= 1:
        raise ValueError("PTZ velocity outside normalized range")
    return number


def _timeout(value):
    if value is None:
        return DEFAULT_TIMEOUT
    # Restrict duration to a time interval, excluding months/dates and signs.
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", value)
    if match is None or not any(part is not None for part in match.groups()):
        raise ValueError("Invalid PTZ timeout")
    try:
        seconds = sum(
            float(part or 0) * factor
            for part, factor in zip(match.groups(), (3600, 60, 1))
        )
    except (ValueError, OverflowError) as exc:
        raise ValueError("Invalid PTZ timeout") from exc
    if not math.isfinite(seconds) or seconds < MIN_TIMEOUT:
        raise ValueError("PTZ timeout too short")
    return min(seconds, MAX_TIMEOUT)


def _boolean(value, default):
    if value is None:
        return default
    if value not in ("true", "false", "0", "1"):
        raise ValueError("Invalid PTZ boolean")
    return value in ("true", "1")


def _slot(token):
    if token is None or re.fullmatch(r"preset[1-5]", token) is None:
        raise ValueError("Unknown native preset slot")
    return int(token[-1])


def _spaces(parent, name):
    spaces = node(parent, name)
    velocity = node(spaces, "tt:ContinuousPanTiltVelocitySpace")
    node(velocity, "tt:URI", PAN_TILT_VELOCITY)
    for axis in ("XRange", "YRange"):
        limits = node(velocity, "tt:" + axis)
        node(limits, "tt:Min", -1)
        node(limits, "tt:Max", 1)


def _node(parent, profile):
    value = node(
        parent,
        "tptz:PTZNode",
        token=profile["token"],
        FixedHomePosition="false",
        GeoMove="false",
    )
    node(value, "tt:Name", profile["token"])
    _spaces(value, "tt:SupportedPTZSpaces")
    node(value, "tt:MaximumNumberOfPresets", 5)
    node(value, "tt:HomeSupported", "false")


def configuration(parent, name, profile):
    """Write the same fixed PTZ configuration used by Media profile responses."""
    value = node(parent, name, token=profile["token"])
    node(value, "tt:Name", profile["token"])
    node(value, "tt:UseCount", 1)
    node(value, "tt:NodeToken", profile["token"])
    node(value, "tt:DefaultContinuousPanTiltVelocitySpace", PAN_TILT_VELOCITY)
    node(value, "tt:DefaultPTZTimeout", "PT0.6S")


def handle_ptz(response, action, item, request, registry):
    """Fill a PTZ response or raise ValueError for the dispatcher's SOAP fault.

    registry.ptz performs transport authorization, bounded movement, and native
    preset acknowledgements. This layer validates XML before any registry call.
    """
    if not item.get("ptz"):
        raise ValueError("PTZ disabled for this export")
    if action == "GetServiceCapabilities":
        node(
            response,
            "tptz:Capabilities",
            EFlip="false",
            Reverse="false",
            GetCompatibleConfigurations="false",
            MoveStatus="true",
            StatusPosition="false",
        )
    elif action == "GetNodes":
        for profile in item["profiles"]:
            _node(response, profile)
    elif action == "GetNode":
        _node(response, _profile(item, _text(request, "NodeToken")))
    elif action == "GetConfigurations":
        for profile in item["profiles"]:
            configuration(response, "tptz:PTZConfiguration", profile)
    elif action == "GetConfiguration":
        configuration(
            response,
            "tptz:PTZConfiguration",
            _profile(item, _text(request, "PTZConfigurationToken")),
        )
    elif action == "GetConfigurationOptions":
        _profile(item, _text(request, "ConfigurationToken"))
        profile_token = _text(request, "ProfileToken", required=False)
        if profile_token is not None:
            _profile(item, profile_token)
        options = node(response, "tptz:PTZConfigurationOptions")
        _spaces(options, "tt:Spaces")
        timeout = node(options, "tt:PTZTimeout")
        node(timeout, "tt:Min", "PT0.08S")
        node(timeout, "tt:Max", "PT5S")
    elif action in {
        "ContinuousMove",
        "Stop",
        "GetStatus",
        "GetPresets",
        "GotoPreset",
        "SetPreset",
        "RemovePreset",
    }:
        token = _text(request, "ProfileToken")
        _profile(item, token)

        def call(operation, parameters):
            return registry.ptz(item["export_id"], token, operation, parameters)

        if action == "ContinuousMove":
            velocities = request.findall("tptz:Velocity", NS)
            if len(velocities) != 1:
                raise ValueError("Missing velocity")
            velocity = velocities[0]
            axes = velocity.findall("tt:PanTilt", NS)
            if len(axes) != 1 or len(velocity) != 1:
                raise ValueError("Only PanTilt velocity is supported")
            pan_tilt = axes[0]
            if pan_tilt.get("space", PAN_TILT_VELOCITY) != PAN_TILT_VELOCITY:
                raise ValueError("Unsupported PTZ space")
            call(
                "continuous_move",
                {
                    "x": _number(pan_tilt.get("x")),
                    "y": _number(pan_tilt.get("y")),
                    "timeout": _timeout(_text(request, "Timeout", False)),
                },
            )
        elif action == "Stop":
            pan_tilt = _boolean(_text(request, "PanTilt", False), True)
            zoom = _boolean(_text(request, "Zoom", False), False)
            if zoom:
                raise ValueError("Zoom unavailable")
            call("stop", {"pan_tilt": pan_tilt, "zoom": zoom})
        elif action == "GetStatus":
            result = call("status", {})
            status = node(response, "tptz:PTZStatus")
            movement = node(status, "tt:MoveStatus")
            state = result.get("moving")
            node(
                movement,
                "tt:PanTilt",
                "MOVING" if state is True else "IDLE" if state is False else "UNKNOWN",
            )
            node(
                status,
                "tt:UtcTime",
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            )
        elif action == "GetPresets":
            result = call("get_presets", {})
            presets = result.get("presets", []) if isinstance(result, dict) else result
            for preset in presets:
                slot = preset["slot"]
                if type(slot) is not int or not 1 <= slot <= 5:
                    raise ValueError("Invalid native preset slot")
                value = node(response, "tptz:Preset", token="preset" + str(slot))
                node(value, "tt:Name", preset.get("name") or "Preset " + str(slot))
        else:
            if request.find("tptz:Speed", NS) is not None:
                raise ValueError("Preset speed is unavailable")
            preset_token = _text(request, "PresetToken", action != "SetPreset")
            slot = _slot(preset_token) if preset_token is not None else None
            params = {"slot": slot}
            if action == "SetPreset":
                name = _text(request, "PresetName", False)
                if name is not None and len(name) > 128:
                    raise ValueError("Preset name too long")
                params["name"] = name
                result = call("set_preset", params)
                confirmed = result.get("slot")
                if type(confirmed) is not int or not 1 <= confirmed <= 5:
                    raise ValueError("Native preset slot unconfirmed")
                node(response, "tptz:PresetToken", "preset" + str(confirmed))
            else:
                call(
                    "goto_preset" if action == "GotoPreset" else "remove_preset", params
                )
    else:
        raise ValueError("Unsupported PTZ operation")
