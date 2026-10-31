# Deployment

## Docker Compose on Linux

Prerequisites: Docker Engine, Docker Compose, a compatible CS2/PPPP camera reachable on a private network, and an O-Kam account with access to it. Vendor services must be reachable for account login and transport bootstrap.

For encrypted account-issued camera credentials, supply your own compatible legacy official client at `secrets/SuperIPCam.exe`. The directory is mounted read-only. No proprietary executable or embedded vendor key is bundled; the file is inspected as data and never executed.

```sh
docker compose up -d
docker compose ps
```

Compose builds and starts three services:

| Service | Purpose |
| --- | --- |
| `init` | Creates a random private gateway token in the shared named volume; exits after initialization. |
| `bridge` | Python API, bound to `127.0.0.1:8098` by default. |
| `web` | Static dashboard and same-origin nginx API proxy, bound to `127.0.0.1:8080` by default. |

The web service starts after the API health check passes. `/health` reports API liveness; it does not test camera availability or vendor connectivity. The gateway token is supplied privately by nginx, never configured in browser JavaScript.

Optional `.env` settings:

```dotenv
WEB_LISTEN=127.0.0.1
WEB_PORT=8080
BRIDGE_PORT=8098
```

Set `WEB_LISTEN=0.0.0.0` to serve the dashboard on the host's network interfaces. The API stays on loopback. Allow access only from trusted clients and use a VPN or HTTPS reverse proxy for remote access. The bundled listeners use HTTP; login credentials, cookies and video require transport protection on untrusted networks.

```sh
docker compose logs --tail=100 bridge web
docker compose down
```

Stopping or restarting the API discards account sessions and active connections. The named gateway volume survives `down`; `down -v` deletes it, and the next startup creates a new token. Before sharing logs, remove identifiers, private addresses and any secrets.

## Docker Desktop

Use Compose 2.24.4+ and the supplied override:

```sh
docker compose -f compose.yaml -f compose.desktop.yaml up -d
```

This uses an ordinary Docker network with a published dashboard port and an internal API. The native UDP connection must traverse Docker Desktop NAT; use an explicit private camera IPv4 address because broadcast discovery may not cross it. If the VM cannot reach the camera transport, run the API natively. Linux should use the default host-network Compose file for direct LAN access. If the dashboard port is occupied, set `WEB_PORT` to a free port in `.env`.

## Native API and separate web frontend

Use Python 3.12+ and install FFmpeg through your operating system's package manager. From the project directory:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m okam_bridge api --listen 127.0.0.1 --port 8098 \
  --credential-client /path/to/SuperIPCam.exe
```

Omit `--credential-client` only when encrypted credential decoding is not needed. `BRIDGE_CREDENTIAL_CLIENT` is an alternative to that flag. Native API mode serves `/docs/` and `/openapi.json`; it does not serve the dashboard.

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
  -e WEB_LISTEN=127.0.0.1 -e WEB_PORT=8080 -e BRIDGE_PORT=8098 \
  --mount type=bind,src=/private/path/token,dst=/run/bridge/gateway-token,readonly \
  okam-local-web
```

This frontend configuration expects the API on host loopback. Docker Desktop networking may not provide that path; adapt the nginx upstream for your environment or serve the frontend through a local nginx installation. Keep the browser and API behind one origin; simply opening `web/index.html` as a file is not a supported deployment.

## Connection troubleshooting

| Symptom | Check |
| --- | --- |
| Account login fails | Account credentials and vendor HTTPS reachability. |
| `password_decoder_required` | Provide the official client file and restart/reconnect as needed. |
| `credential_key_not_found` | The supplied client may be incompatible; do not publish the file or extracted keys. |
| No LAN reply | Camera private IPv4, host routing, firewall and UDP transport reachability. |
| No video | Correct native credentials, compatible transport, FFmpeg, camera state and selected lens. |
| Open native service port but no RTSP/ONVIF login | TCP availability is not protocol or credential verification. |

The older `setup` / `serve` CLI workflow remains available for a private cached camera configuration. It stores native camera credentials in the private config and differs from the account-session API workflow; keep that file out of source control.
