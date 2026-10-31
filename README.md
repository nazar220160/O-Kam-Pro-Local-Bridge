# O-Kam Pro Local Bridge

**Your cameras. Your network. Your API.**

[![Version 0.6.0](https://img.shields.io/badge/version-0.6.0-95d75d)](CHANGELOG.md)
[![License MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![API reference](https://img.shields.io/badge/API-OpenAPI_3.1-527ac9)](docs/api.md)

A self-hosted dashboard and HTTP API for compatible O-Kam Pro cameras using the CS2/PPPP protocol. View local video, switch lenses, move PTZ cameras, inspect metadata and send validated native controls from one interface.

[Quick start](#quick-start) · [Deployment](docs/deployment.md) · [API](docs/api.md) · [Security](SECURITY.md) · [Русский](README.ru.md)

![O-Kam Local Bridge dashboard sign-in](docs/assets/login.jpg)

## What it does

- Browser live view, snapshots, MJPEG and original H.264 output.
- Multiple lens views, including three-lens camera layouts where supported.
- High, medium and low native quality selection.
- PTZ, presets, image settings and model-dependent native controls.
- Account camera catalog, redacted metadata and a control console.
- Separate Python API and static nginx dashboard, with a documented OpenAPI contract.

**Compatibility matters:** this bridge supports the CS2/PPPP transport family, not every camera sold under the O-Kam name. Cameras must be reachable on your LAN or a routed private network. Account login and transport bootstrap contact vendor services; this is not a cloud relay or WAN video transport.

Audio streaming, two-way talk, SD recording playback, VP transport and a bridge-hosted RTSP server are not implemented. Native camera capability flags do not prove that an RTSP or ONVIF daemon is running. Independent service toggles are not verified and are disabled in the dashboard.

## Quick start

Use Docker Engine on Linux with Docker Compose. Host networking lets the bridge reach camera UDP discovery and native transport directly.

```sh
git clone https://github.com/nazar220160/O-Kam-Pro-Local-Bridge.git
cd O-Kam-Pro-Local-Bridge
```

If your account supplies **encrypted camera passwords**, place your own compatible legacy official `SuperIPCam.exe` at `secrets/SuperIPCam.exe` before connecting cameras. The project does not include or download this proprietary file. It reads the file as data to decode account-issued credentials; it never executes it. Not every official client version is compatible.

```sh
docker compose up -d
```

Open [localhost:8080](http://localhost:8080), sign in with your O-Kam account, select a camera and connect. The dashboard starts separately from the API; Compose builds both and initializes their private gateway token automatically. No manual gateway token setup is needed.

Default listeners: dashboard `127.0.0.1:8080`, API `127.0.0.1:8098`. The API reference is available through the dashboard at [/docs/](http://localhost:8080/docs/) and [/openapi.json](http://localhost:8080/openapi.json).

For access from another device on a trusted LAN, create `.env`:

```dotenv
WEB_LISTEN=0.0.0.0
WEB_PORT=8080
BRIDGE_PORT=8098
```

Then run `docker compose up -d` again. Read the [deployment guide](docs/deployment.md) before exposing a listener beyond your machine. For Docker Desktop on macOS/Windows, use `docker compose -f compose.yaml -f compose.desktop.yaml up -d`. This publishes the dashboard normally and keeps the API internal. Enter the camera IP explicitly; UDP broadcast discovery may not cross Docker NAT. A native API is an alternative if camera transport cannot traverse the VM network.

## Native API

Install Python 3.12+, FFmpeg on `PATH`, and the Python dependencies:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m okam_bridge api --port 8098
```

The API serves JSON and API documentation. The dashboard is the separate `web/` service. For encrypted camera credentials, add `--credential-client /path/to/SuperIPCam.exe`. See [deployment](docs/deployment.md) for access protection and frontend configuration, and [API examples](docs/api.md) for login, video and controls.

## Project

Independent community software, unaffiliated with O-Kam, VStarcam or their vendors. Firmware and model behavior vary; report reproducible compatibility details without publishing identifiers or secrets.

Contributions are welcome: [CONTRIBUTING.md](CONTRIBUTING.md). MIT licensed; attribution and inherited code are documented in [THIRD_PARTY.md](THIRD_PARTY.md).
