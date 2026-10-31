"""Read-only, bounded checks of native camera services, not subnet scans."""

from concurrent.futures import ThreadPoolExecutor
import socket

PORTS = (
    (554, "rtsp"),
    (10554, "rtsp"),
    (10555, "rtsp"),
    (10556, "rtsp"),
    (10080, "onvif"),
)


def probe_port(ip, port):
    try:
        with socket.create_connection((ip, port), timeout=1.2):
            return True
    except OSError:
        return False


def inspect_services(camera_id, ip, details):
    # One selected, already validated private camera IP; fixed service ports only.
    with ThreadPoolExecutor(max_workers=len(PORTS)) as pool:
        results = list(
            pool.map(
                lambda item: {
                    "port": item[0],
                    "service": item[1],
                    "open": probe_port(ip, item[0]),
                },
                PORTS,
            )
        )
    groups = details.get("groups", {})
    values = {
        k: v
        for group in groups.values()
        if isinstance(group, dict)
        for k, v in group.items()
    }
    evidence = {
        k: values[k]
        for k in ("onvif_support_enable", "support_Plaintext_Pwd", "ExUserSwitch")
        if k in values
    }
    return {
        "camera_id": camera_id,
        "ip": ip,
        "capabilities": {
            "onvif": details.get("capabilities", {}).get(
                "onvif", {"available": None, "evidence": {}}
            ),
            "rtsp": {"available": None, "evidence": evidence},
        },
        "ports": results,
        "probe_type": "tcp_connect",
        "protocol_verified": False,
        "configuration": {
            "onvif": {
                "writable": False,
                "reason": "No verified independent ONVIF service switch for this firmware.",
            },
            "rtsp": {
                "writable": False,
                "reason": "No verified independent RTSP daemon switch for this firmware.",
            },
            "plaintext_password": {
                "writable": True,
                "action": "plaintext_password",
                "supported": (
                    None
                    if "support_Plaintext_Pwd" not in values
                    else str(values["support_Plaintext_Pwd"]) != "0"
                ),
                "enabled": (
                    None
                    if "ExUserSwitch" not in values
                    else str(values["ExUserSwitch"]) == "1"
                ),
            },
        },
        "instructions": [
            "Set the native local-access password explicitly using plaintext_password. Firmware may reject unsupported commands.",
            "Then refresh camera parameters and check native ports again. An open TCP port does not verify RTSP or ONVIF authentication.",
            "Typical RTSP address: rtsp://<camera-ip>:10554/tcp/av0_0. Enter admin and the configured local password in your player.",
        ],
        "references": [
            "https://shop.vstarcam.cn/docs/cgi-command-list/",
            "https://open.veesky.com/docs/open-rtsp/",
        ],
    }
