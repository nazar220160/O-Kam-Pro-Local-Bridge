# Deployment

## Docker Compose on Linux

Prerequisites: Docker Engine, Docker Compose, a compatible CS2/PPPP camera reachable on a private network, and an O-Kam account with access to it. Vendor services must be reachable for account login and transport bootstrap.

Encrypted account-issued camera credentials are decoded in-process using the supported securityPwd protocol. No official-client executable, credentials mount or manual file download is required.

```sh
docker compose up -d
docker compose ps
```

Compose builds the bridge and dashboard and starts four services:

| Service | Purpose |
| --- | --- |
| `init` | Creates a random private gateway token in the shared named volume; exits after initialization. |
| `bridge` | Python API, bound to `127.0.0.1:8098` by default. |
| `web` | Static dashboard and same-origin nginx API proxy, bound to `0.0.0.0:8080` by default. |
| `mediamtx` | Separate upstream MediaMTX 1.21.2 container for optional RTSP/TCP publication, listening on `0.0.0.0:8554` by default. |

The web service starts after the API health check passes. `/health` reports API liveness; it does not test camera availability or vendor connectivity. The gateway token is supplied privately by nginx, never configured in browser JavaScript.

Optional `.env` settings:

```dotenv
WEB_LISTEN=0.0.0.0
WEB_PORT=8080
BRIDGE_PORT=8098
RTSP_LISTEN=0.0.0.0
RTSP_PORT=8554
ONVIF_LISTEN=0.0.0.0
ONVIF_PORT=8899
```

The dashboard listens on host network interfaces by default. Set `WEB_LISTEN=127.0.0.1` for host-only access. The API stays on loopback. Allow access only from trusted clients and use a VPN or HTTPS reverse proxy for remote access. The bundled listeners use HTTP; login credentials, cookies and video require transport protection on untrusted networks.

```sh
docker compose logs --tail=100 bridge web
docker compose down
```

Stopping or restarting the API discards account sessions and active connections. The named gateway and recordings volumes survive `down`; `down -v` deletes both, including all server recordings, SD cache and their manifest. The next startup creates a new gateway token. Before sharing logs, remove identifiers, private addresses and any secrets.

## Update an existing Docker installation

```sh
git pull
docker compose up -d --build
```

The rebuild is required when updating source on a machine with an existing image. From 0.8.1 onward, no `secrets/SuperIPCam.exe` is needed. Existing recordings and gateway volumes are retained. Log in and reconnect after the API is recreated. An existing `WEB_LISTEN=127.0.0.1` override still restricts dashboard access; set it to `0.0.0.0` for LAN access.

## macOS: native camera API, Docker dashboard

Docker Desktop NAT can discard the camera's first UDP reply because it comes from a dynamic source port rather than the discovery port. An explicit camera IP does not fix this behavior. The same camera and bridge code may work directly on macOS while failing inside both bridge and host Docker networking.

Use:

```sh
./start-macos.sh
```

Prerequisites: Python 3.11+, FFmpeg (`brew install ffmpeg`) and running Docker Desktop. The script prepares a local Python environment, starts the protected API on macOS loopback, stops the previous container API, and starts the Docker web and MediaMTX services using `compose.macos.yaml`. Nginx reaches the API through `host.docker.internal`; the browser still uses one origin. `.env` controls `WEB_PORT` and `BRIDGE_PORT` as before.

Runtime files are under `.runtime/`: API log, PID and gateway token. The directory is mode 0700 and excluded from Git; only the gateway file is mounted read-only into nginx. Account sessions remain memory-only. A machine reboot requires rerunning `./start-macos.sh`. `docker compose down` alone does not stop the native API process.

If updating an already running native API, stop that process before rerunning the launcher. A listener using a different gateway token is rejected instead of silently attaching to it. The launcher does not change global Docker Desktop settings or restart unrelated containers.

`compose.desktop.yaml` remains an experimental all-container option for Docker Desktop; UDP camera access is not guaranteed. Linux should use the standard host-network Compose deployment.

## Native API and separate web frontend

Use Python 3.12+ and install FFmpeg through your operating system's package manager. From the project directory:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m okam_bridge api --listen 127.0.0.1 --port 8098
```

Credential decoding is built in. `--credential-client` / `BRIDGE_CREDENTIAL_CLIENT` remains an optional compatibility override for alternate vendor salts, and is not configured by Compose or the macOS launcher. Native API mode serves `/docs/` and `/openapi.json`; it does not serve the dashboard.

For a standalone protected API, set `BRIDGE_ACCESS_TOKEN` to a strong random secret before launch, or use `--access-token-file /private/path/token`. The bridge access token protects account login; successful login then returns an account session token. Supply the bridge token as `Authorization: Bearer <bridge-access-token>` on login. A non-loopback API listener requires access protection. Keep the API private whenever possible.

The `web/` image can proxy a native API on Linux using host networking. Supply a private token file shared with the API. It must be readable by nginx UID 101 (for example through a suitably restricted group or ACL):

```sh
# /private/path/token must already contain a strong random token.
python -m okam_bridge api --port 8098 --access-token-file /private/path/token
```

In another terminal:

```sh
docker build -t okam-local-web ./web
docker run --rm --network host \
  -e WEB_LISTEN=0.0.0.0 -e WEB_PORT=8080 -e BRIDGE_PORT=8098 \
  --mount type=bind,src=/private/path/token,dst=/run/bridge/gateway-token,readonly \
  okam-local-web
```

This frontend configuration expects the API on host loopback. Docker Desktop networking may not provide that path; adapt the nginx upstream for your environment or serve the frontend through a local nginx installation. Keep the browser and API behind one origin; simply opening `web/index.html` as a file is not a supported deployment.

## Bridge publication listeners

RTSP is served by MediaMTX over TCP; no camera is published until explicitly enabled. The API lazily opens the ONVIF listener after ONVIF publication is enabled, using `ONVIF_LISTEN` / `ONVIF_PORT` (defaults `0.0.0.0:8899`). After all publications are disabled, that listener remains open until API restart, but revoked or missing publication paths return 404. See [bridge exports](bridge-exports.md) for VLC/NVR setup and lifecycle.

For a manually deployed native API, `BRIDGE_RTSP_INTERNAL_URL` is its credential-free upstream base URL (default `rtsp://127.0.0.1:8554`); `BRIDGE_RTSP_PORT` is the public port advertised to clients. `BRIDGE_ONVIF_LISTEN` and `BRIDGE_ONVIF_PORT` control its ONVIF listener. Compose and the macOS launcher map the `.env` settings above to these variables. Start MediaMTX with the supplied `deploy/mediamtx.yml` and a reachable HTTP authorization callback at `/api/exports/auth`; the standalone API command alone does not start an RTSP server.

On macOS, the API continues to handle physical-camera UDP natively, preserving the 0.6.1 transport fix. MediaMTX publishes its TCP port from Docker. The all-container Desktop alternative remains experimental; WS-Discovery multicast generally cannot cross container NAT, so use the returned manual ONVIF address.

## Connection troubleshooting

| Symptom | Check |
| --- | --- |
| Account login fails | Account credentials and vendor HTTPS reachability. |
| `encrypted_credentials_invalid` | Refresh the account catalog and reconnect; the account record may be stale or use an unsupported credential variant. |
| `credential_key_not_found` | Only relevant to an explicitly supplied legacy client-file override; remove the override for the built-in protocol. |
| No LAN reply | Camera private IPv4, host routing, firewall and UDP transport reachability. |
| No video | Correct native credentials, compatible transport, FFmpeg, camera state and selected lens. |
| Open native service port but no RTSP/ONVIF login | TCP availability is not protocol or credential verification. |

The older `setup` / `serve` CLI workflow remains available for a private cached camera configuration. It stores native camera credentials in the private config and differs from the account-session API workflow; keep that file out of source control.


## Persistent archive storage

The Linux bridge mounts a writable `recordings` named volume at `/recordings` while retaining its read-only container root filesystem. `BRIDGE_RECORDINGS_DIR=/recordings` selects it. Native macOS defaults to `.runtime/recordings` (private directory, excluded from Git); set `BRIDGE_RECORDINGS_DIR` before starting the API to use another disk. Recording and SD import remain opt-in, and recording workers do not resume after restart. Retained files are accessible after signing into the same account again.

Back up the SQLite manifest and clips together while the API is stopped. Monitor disk usage across all cameras: retention/quota are per camera and are enforced when files complete, not a global capacity guarantee. See [archive behavior and limits](bridge-exports.md#server-and-sd-archives).
