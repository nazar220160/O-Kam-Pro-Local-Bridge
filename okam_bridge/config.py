"""Private configuration. Cloud credentials are never persisted."""

import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile


def validate_server(config):
    if not isinstance(config, dict):
        raise ValueError("Configuration must be an object")
    if not isinstance(config.get("access_token", ""), str):
        raise ValueError("access_token must be a string")
    idle = config.get("idle_timeout", 30)
    if type(idle) not in (int, float) or not 1 <= idle <= 3600:
        raise ValueError("idle_timeout must be 1–3600 seconds")
    host = config.get("listen", "127.0.0.1")
    if not isinstance(host, str):
        raise ValueError("listen must be a host string")
    if (
        host not in ("127.0.0.1", "localhost")
        and len(config.get("access_token", "")) < 16
    ):
        raise ValueError(
            "A non-loopback listen address requires an access_token of at least 16 characters"
        )
    port = config.get("port", 8099)
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("port must be an integer between 0 and 65535")
    return config


def validate_config(config):
    validate_server(config)
    if (
        not isinstance(config, dict)
        or not isinstance(config.get("cameras"), list)
        or not config["cameras"]
    ):
        raise ValueError("cameras must contain at least one camera")
    ids = set()
    for c in config["cameras"]:
        if (
            not isinstance(c, dict)
            or not isinstance(c.get("id"), str)
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", c.get("id", ""))
        ):
            raise ValueError(
                "Camera id must contain 1–64 ASCII letters, digits, underscores or hyphens"
            )
        if c["id"] in ids:
            raise ValueError("Duplicate camera id: " + c["id"])
        ids.add(c["id"])
        try:
            ipaddress.IPv4Address(c["ip"])
            if c.get("broadcast"):
                ipaddress.IPv4Address(c["broadcast"])
        except (ValueError, KeyError):
            raise ValueError(
                "Camera ip and optional broadcast must be IPv4 addresses"
            ) from None
        if not all(
            isinstance(c.get(k), str) and c[k]
            for k in ("transport_uid", "service_parameter")
        ):
            raise ValueError(
                "Camera needs transport_uid and service_parameter; run setup first"
            )
        for field in (
            "password",
            "password_env",
            "compatibility_password",
            "username",
            "name",
        ):
            if field in c and not isinstance(c[field], str):
                raise ValueError("Camera " + field + " must be a string")
        if type(c.get("substream", 2)) is not int or c.get("substream", 2) not in (
            0,
            1,
            2,
        ):
            raise ValueError("substream must be 0, 1 or 2")
        if not c.get("password") and not c.get("password_env"):
            raise ValueError("Camera needs password or password_env")
        if "account_id" in c and (
            not isinstance(c["account_id"], str)
            or not c["account_id"].isascii()
            or not c["account_id"].isdigit()
        ):
            raise ValueError("account_id must be a numeric string from account setup")
        ports = c.get("ports", [32108, 32100])
        if (
            not isinstance(ports, list)
            or not ports
            or len(ports) > 16
            or any(type(p) is not int or not 1 <= p <= 65535 for p in ports)
        ):
            raise ValueError("Camera ports must be a list of 1–16 UDP ports")
    return config


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_config(config)
    for c in config["cameras"]:
        if c.get("password_env"):
            name = c["password_env"]
            if not os.environ.get(name):
                raise ValueError(
                    "Missing camera password environment variable: " + name
                )
            c["password"] = os.environ[name]
    return config


def save_config(path, config):
    validate_config(config)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
