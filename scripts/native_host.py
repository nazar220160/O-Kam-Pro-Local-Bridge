"""Start a loopback-only native macOS API and its separate Docker dashboard."""

import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def prepare_runtime(root):
    runtime = root / ".runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    runtime.chmod(0o700)
    path = runtime / "gateway-token"
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as out:
            out.write(secrets.token_urlsafe(48))
    token = path.read_text().strip()
    if (
        not 32 <= len(token) <= 512
        or not token.isascii()
        or not all(c.isalnum() or c in "-_" for c in token)
    ):
        raise RuntimeError("Invalid private gateway token in .runtime.")
    # The parent is host-user-only; the file is explicitly shared with nginx UID 101.
    path.chmod(0o644)
    return path


def native_command(root, python, port):
    command = [
        python,
        "-m",
        "okam_bridge",
        "api",
        "--listen",
        "127.0.0.1",
        "--port",
        str(port),
        "--access-token-file",
        str(root / ".runtime/gateway-token"),
    ]
    client = root / "secrets/SuperIPCam.exe"
    if client.is_file():
        command += ["--credential-client", str(client)]
    return command


def native_environment():
    env = dict(os.environ)
    env.pop("BRIDGE_ACCESS_TOKEN", None)
    env.pop("BRIDGE_ACCESS_TOKEN_FILE", None)
    return env


def backend_ready(port, token):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
            health = json.loads(r.read(8192))
        if health.get("mode") != "api" or not health.get("ok"):
            return False
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/account", headers={"X-Bridge-Gateway": token}
        )
        try:
            urllib.request.urlopen(request, timeout=1).close()
        except urllib.error.HTTPError as e:
            return (
                e.code == 401
                and json.loads(e.read(8192)).get("error") == "account_login_required"
            )
    except (OSError, ValueError):
        pass
    return False


def compose_settings(root):
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "compose.yaml",
            "-f",
            "compose.macos.yaml",
            "config",
            "--format",
            "json",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    web = json.loads(result.stdout)["services"]["web"]
    return int(web["environment"]["BRIDGE_PORT"]), int(web["ports"][0]["published"])


def start(root):
    if sys.platform != "darwin":
        raise RuntimeError(
            "Use docker compose up -d on Linux; this launcher is for macOS."
        )
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is required: brew install ffmpeg")
    if not shutil.which("docker"):
        raise RuntimeError("Docker Desktop is required for the web dashboard.")
    port, web_port = compose_settings(root)
    if not 1024 <= port <= 65535:
        raise RuntimeError("BRIDGE_PORT must be between 1024 and 65535.")
    token_path = prepare_runtime(root)
    token = token_path.read_text().strip()
    if not backend_ready(port, token):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(
                    f"Port {port} is occupied by another API; stop it or choose BRIDGE_PORT."
                )
        log_path = root / ".runtime/bridge.log"
        fd = os.open(log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "ab") as log:
            child = subprocess.Popen(
                native_command(root, sys.executable, port),
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=native_environment(),
            )
        (root / ".runtime/bridge.pid").write_text(str(child.pid))
        for _ in range(60):
            if backend_ready(port, token):
                break
            if child.poll() is not None:
                raise RuntimeError("Native API exited; see .runtime/bridge.log.")
            time.sleep(0.25)
        else:
            child.terminate()
            raise RuntimeError(
                "Native API did not become ready; see .runtime/bridge.log."
            )
    # A previously running container API must not remain the camera endpoint.
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "compose.yaml",
            "-f",
            "compose.desktop.yaml",
            "stop",
            "bridge",
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "compose.yaml",
            "-f",
            "compose.macos.yaml",
            "up",
            "-d",
            "--build",
            "--wait",
            "web",
        ],
        cwd=root,
        check=True,
    )
    print("Native camera API is ready. Dashboard: http://127.0.0.1:" + str(web_port))


if __name__ == "__main__":
    try:
        start(Path(__file__).resolve().parents[1])
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as e:
        print("Startup failed: " + str(e), file=sys.stderr)
        raise SystemExit(1)
