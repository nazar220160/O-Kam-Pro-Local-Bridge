# O-Kam Pro Local Bridge

**Your cameras. Your network. Your API.**

[![Version 0.12.1](https://img.shields.io/badge/version-0.12.1-95d75d)](CHANGELOG.md)
[![License MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![API reference](https://img.shields.io/badge/API-OpenAPI_3.1-527ac9)](docs/api.md)

A self-hosted dashboard and HTTP API for compatible O-Kam Pro cameras using CS2/PPPP or VP/CPPPP2. View video over your LAN or the vendor relay, switch lenses, inspect metadata and control supported cameras from one interface.

[Quick start](#quick-start) · [Deployment](docs/deployment.md) · [API](docs/api.md) · [Bridge exports](docs/bridge-exports.md) · [Security](SECURITY.md) · [Русский](README.ru.md)

## What it does

- Responsive Next.js and TypeScript dashboard with shadcn/ui components, TanStack Query and Axios.
- Browser live view, snapshots, MJPEG and original H.264 output.
- Separate local and O-Kam Pro relay connection buttons; the selected source survives restart.
- Optional bridge RTSP/TCP publication and ONVIF Device/Media, PTZ, PullPoint events and archive services, with one profile per observed lens.
- Multiple lens views, including three-lens camera layouts where supported.
- High, medium and low native quality selection.
- PTZ, presets, image settings and model-dependent native controls.
- Account camera catalog, redacted metadata and a control console.
- Opt-in server recording with retention/quota, SD-card clip import, authenticated downloads and RTSP replay.
- Encrypted persistent sessions and automatic camera/publication/recording restoration after restart.
- Separate Python API and frontend, with a documented OpenAPI contract. Docker builds the Next.js static export and serves it through nginx.

CS2/PPPP cameras can use LAN or O-Kam Pro relay mode. Compatible VP/CPPPP2 cameras use O-Kam Pro relay mode with H.264 video, metadata, quality selection and bridge publication. The VP adapter currently covers DAS records without a checksum field. VP audio, PTZ, other camera setting changes and SD-card retrieval remain unavailable. Relay mode needs internet access at the bridge and camera. Account login and transport bootstrap contact vendor services in both modes.

Compatible CS2 cameras supply G.711 A-law audio, which the bridge publishes as AAC. Bridge publication copies H.264 without encoding through MediaMTX (TCP 8554 by default). The optional ONVIF endpoint uses port 8899 and authenticated snapshots. WS-Discovery requires multicast reachability. ONVIF supports recording search and forward clip replay. Compatible CS2 cameras also expose bounded pan/tilt, presets and observed status events. Two-way talk, absolute PTZ positions, reverse playback and RTSP clock seeking are unavailable. [Set up bridge exports](docs/bridge-exports.md).

Native camera capability flags do not prove that an RTSP or ONVIF daemon is running. Independent native service toggles remain unverified and disabled; bridge publication does not change the camera’s native ONVIF/RTSP settings.

## Quick start

Use Docker Engine on Linux with Docker Compose. Host networking lets the bridge reach camera UDP discovery and native transport directly.

```sh
git clone https://github.com/nazar220160/O-Kam-Pro-Local-Bridge.git
cd O-Kam-Pro-Local-Bridge
```

Encrypted camera credentials are decoded by the bridge itself. No official PC client, copied executable or extra credentials file is required.

```sh
docker compose up -d
```

Open [localhost:8080](http://localhost:8080), sign in with your O-Kam account, select a camera and choose **Открыть видео** for LAN or **Через O-Kam Pro** for the vendor relay. Relay mode does not require the camera LAN IP. The dashboard starts separately from the API; Compose builds both and initializes their private gateway token automatically. No manual gateway token setup is needed.

Default listeners: dashboard `0.0.0.0:8080`, API `127.0.0.1:8098`. The API reference is available through the dashboard at [/docs/](http://localhost:8080/docs/) and [/openapi.json](http://localhost:8080/openapi.json).

The dashboard is reachable at `http://SERVER_IP:8080` on your trusted LAN. Optional `.env` overrides:

```dotenv
WEB_LISTEN=0.0.0.0
WEB_PORT=8080
BRIDGE_PORT=8098
```

Then run `docker compose up -d` again. Read the [deployment guide](docs/deployment.md) before exposing a listener beyond your machine. On **macOS**, run `./start-macos.sh` instead: it starts the camera API natively and the dashboard plus MediaMTX in Docker. Python 3.11+, FFmpeg and Docker Desktop are required. This avoids Docker Desktop NAT dropping replies from cameras' dynamic UDP ports. The same `.env` port settings apply.

`compose.desktop.yaml` is an experimental all-container alternative; explicit camera IP alone does not guarantee UDP reachability through Docker Desktop. Use the native macOS launcher if the camera is unreachable from the VM.

## Native API

Install Python 3.12+, FFmpeg on `PATH`, and the Python dependencies:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m okam_bridge api --port 8098
```

The API serves JSON and API documentation. The dashboard is the separate `web/` service. Credential decoding is built in; no `--credential-client` argument is needed. See [deployment](docs/deployment.md) for access protection and frontend configuration, and [API examples](docs/api.md) for login, video and controls.

Publication credentials are separate from account, camera and browser-player credentials and appear automatically in selectable text fields when publication is enabled. Account sessions, camera connections and source selection, quality, publication IDs/passwords and enabled server recording are stored in encrypted persistent state and restored automatically after API/container restart. RTSP URLs remain unchanged, so an NVR does not need reconfiguration. Switching between local and relay video retains the publication ID/password and NVR addresses, with a pause while the source reconnects. Explicit logout removes the saved session and stops its publications; disconnect/disable remains off after restart.

## Frontend development

The dashboard source lives in `web/src/`. Use Node.js 22+ and the committed npm lockfile. With the existing bridge/nginx gateway running:

```sh
cd web
npm ci
BRIDGE_DEV_URL=http://127.0.0.1:8080 npm run dev
```

Open [localhost:3000](http://localhost:3000). The development proxy keeps API requests and video on the same browser origin and forwards them to the existing gateway. See [development and build checks](CONTRIBUTING.md#develop-locally). Production uses nginx with the compiled export; Node.js is only required during the Docker build.

## Project

Independent community software, unaffiliated with O-Kam, VStarcam or their vendors. Firmware and model behavior vary; report reproducible compatibility details without publishing identifiers or secrets.

Contributions are welcome: [CONTRIBUTING.md](CONTRIBUTING.md). MIT licensed; attribution and inherited code are documented in [THIRD_PARTY.md](THIRD_PARTY.md).
