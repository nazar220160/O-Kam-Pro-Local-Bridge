"""python -m okam_bridge: setup once, then serve without cloud access."""

import argparse
import getpass
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import threading
from .config import load_config, save_config
from .camera import Camera
from .transport import connect_lan, authenticate, start_video
from .vendor.account import Eye4AccountClient, AccountError
from .vendor.p2p import resolve_client_id, get_service_parameter, P2PError
from .vendor.cs2 import CS2Error
from .web import BridgeServer


def setup(args):
    path = Path(args.config)
    config = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"listen": "127.0.0.1", "port": 8099, "cameras": []}
    )
    account = args.account or input("O-KAM account email: ").strip()
    password = getpass.getpass("O-KAM account password (not saved): ")
    client = Eye4AccountClient()
    try:
        devices = client.enumerate(account, password)
    finally:
        password = ""
    if not devices:
        raise ValueError("No cameras on this account")
    print("Account cameras:")
    for n, d in enumerate(devices, 1):
        print(f"  {n}. {d.name}")
    if args.camera:
        matching = [d for d in devices if d.name == args.camera]
        if len(matching) != 1:
            raise ValueError("Camera name must match exactly one camera")
        device = matching[0]
    else:
        try:
            device = devices[int(input("Camera number: ")) - 1]
        except (ValueError, IndexError):
            raise ValueError("Invalid camera number") from None
    ip = args.ip or input("Camera LAN IPv4 address: ").strip()
    camera_id = args.id or input("Local camera id (ASCII, e.g. yard): ").strip()
    entry = {
        "id": camera_id,
        "name": device.name,
        "ip": ip,
        "transport_uid": resolve_client_id(device.uid),
        "service_parameter": get_service_parameter(resolve_client_id(device.uid)),
        "username": args.username,
        "ports": [32108, 32100],
        "substream": args.substream,
        "account_id": client.user_id,
        "compatibility_password": "888888",
    }
    if args.broadcast:
        entry["broadcast"] = args.broadcast
    if args.capture:
        from .capture import credentials_from_capture
        from .vendor.cs2 import CS2Session

        native_key = CS2Session(entry["transport_uid"], entry["service_parameter"]).key
        entry.update(credentials_from_capture(args.capture, ip, native_key))
        local_password = entry["password"]
    elif args.password_env:
        if not os.environ.get(args.password_env):
            raise ValueError(
                "Set the password environment variable first: " + args.password_env
            )
        entry["password_env"] = args.password_env
        local_password = os.environ[args.password_env]
    elif device.device_password and not args.prompt_password:
        local_password = device.device_password
        entry["password"] = local_password
        print("Using camera credentials supplied to this O-KAM account.")
    else:
        local_password = getpass.getpass(
            "Native CAMERA password (saved to private config): "
        )
        entry["password"] = local_password
    # Validate inputs before sending anything on the LAN or replacing config.
    from .config import validate_config

    validate_config({**config, "cameras": [entry]})
    print("Checking local camera authentication…")
    session = connect_lan(entry)
    try:
        user, camera_password = authenticate(
            session, {**entry, "password": local_password}
        )
        start_video(
            session,
            user,
            camera_password,
            substream=entry["substream"],
            compatibility_password=entry.get("compatibility_password"),
            account_id=entry.get("account_id"),
        )
        from .vendor.cs2 import read_video_frame

        frame, _ = read_video_frame(session, timeout=10)
        if not frame:
            raise ValueError("Camera did not send video")
    finally:
        session.close()
    config["cameras"] = [c for c in config["cameras"] if c["id"] != camera_id] + [entry]
    save_config(path, config)
    print(
        "Camera added. Config contains local camera credentials; account password was not saved."
    )
    print("Start: python -m okam_bridge serve --config " + str(path))


def serve(args):
    config = load_config(args.config)
    ffmpeg = shutil.which(args.ffmpeg or "ffmpeg")
    if not ffmpeg:
        raise ValueError(
            "FFmpeg is required. Install it and add ffmpeg to PATH, or use --ffmpeg /path/to/ffmpeg"
        )
    cameras = {
        c["id"]: Camera(c, ffmpeg, idle_timeout=config.get("idle_timeout", 30))
        for c in config["cameras"]
    }
    server = BridgeServer(
        (config.get("listen", "127.0.0.1"), config.get("port", 8099)),
        cameras,
        config.get("access_token", ""),
    )

    def terminate(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    host, port = server.server_address
    print(f"O-KAM Local Bridge: http://{host}:{port}", flush=True)
    print("Runtime: cached configuration, LAN video only. Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        for c in cameras.values():
            c.stop()


def read_access_token(env_name, token_file=None):
    value = os.environ.get(env_name, "")
    if not value and token_file:
        value = Path(token_file).read_text().strip()
        if len(value) < 16 or len(value) > 512:
            raise ValueError("Access token file must contain 16–512 characters")
    return value


def app(args):
    from .accounts import AccountManager, LANBackend
    from .app_server import AppServer

    ffmpeg = shutil.which(args.ffmpeg or "ffmpeg")
    if not ffmpeg:
        raise ValueError("FFmpeg is required on PATH")
    token = read_access_token(args.access_token_env, args.access_token_file)
    from .config import validate_server

    validate_server({"listen": args.listen, "port": args.port, "access_token": token})
    manager = AccountManager(
        backend=LANBackend(
            ffmpeg, args.credential_client or os.environ.get("BRIDGE_CREDENTIAL_CLIENT")
        )
    )
    server = AppServer((args.listen, args.port), manager, token)

    def terminate(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    print(
        f"O-Kam Bridge API: http://{server.server_address[0]}:{server.server_address[1]}",
        flush=True,
    )
    print(
        "API reference: /docs/ · OpenAPI: /openapi.json · Web dashboard runs separately.",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(
        description="Portable O-KAM CS2/PPPP LAN camera bridge"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser(
        "api",
        aliases=["app"],
        help="Standalone HTTP API; dashboard is a separate service",
    )
    p.add_argument("--listen", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8098)
    p.add_argument(
        "--credential-client",
        help="Optional legacy client-file override for alternate credential protocols; standard decoding is built in",
    )
    p.add_argument("--ffmpeg")
    p.add_argument("--access-token-env", default="BRIDGE_ACCESS_TOKEN")
    p.add_argument(
        "--access-token-file", default=os.environ.get("BRIDGE_ACCESS_TOKEN_FILE")
    )
    p = sub.add_parser(
        "setup", help="Add/update a camera; account used only for bootstrap"
    )
    p.add_argument("--config", default="config.private.json")
    p.add_argument("--account")
    p.add_argument("--camera")
    p.add_argument("--ip")
    p.add_argument("--id")
    p.add_argument("--substream", type=int, choices=(0, 1, 2), default=1)
    p.add_argument("--prompt-password", action="store_true")
    p.add_argument("--capture", help="Optional classic PCAP from your own app session")
    p.add_argument("--username", default="admin")
    p.add_argument("--broadcast")
    p.add_argument("--password-env")
    p = sub.add_parser(
        "serve", help="Start local browser/VLC bridge without cloud requests"
    )
    p.add_argument("--config", default="config.private.json")
    p.add_argument("--ffmpeg")
    args = parser.parse_args()
    try:
        if args.command == "setup":
            setup(args)
        elif args.command in ("app", "api"):
            app(args)
        else:
            serve(args)
    except (ValueError, OSError, AccountError, P2PError, CS2Error) as error:
        # Avoid third-party exception text, which could contain identifiers.
        if isinstance(error, ValueError):
            print("Configuration: " + str(error), file=sys.stderr)
        elif isinstance(error, CS2Error) and (
            str(error).startswith("video_start_rejected:")
            or str(error)
            in (
                "video_authorization_rejected",
                "camera_password_rejected",
                "no_lan_reply",
            )
        ):
            print(
                "Camera: "
                + str(error)
                + ". Check native camera credentials or use --capture import.",
                file=sys.stderr,
            )
        else:
            print(
                "Could not complete the operation. Check credentials, camera LAN access, vendor bootstrap services and FFmpeg.",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
