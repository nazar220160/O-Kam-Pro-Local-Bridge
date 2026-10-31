# HTTP API · v0.12.0

The Python API is independent of the dashboard. With Compose, use `http://localhost:8080` for both the dashboard and proxied API. For a native process started with `python -m okam_bridge api --port 8098`, use `http://localhost:8098`.

The running service provides a self-contained reference at `/docs/` and an OpenAPI 3.1 contract at `/openapi.json`. [api_schema.py](../okam_bridge/api_schema.py) is the source contract, including supported actions and parameter ranges.

## Authentication

Log in using your O-Kam account. Login contacts vendor HTTPS services; encrypted session/transport state and the vendor protocol password digest are persisted for automatic recovery; the original account password is not stored. The response sets an HttpOnly, SameSite=Strict `okam_account` cookie and returns `session_token` for API clients.

```sh
curl -c session.cookies -H 'Content-Type: application/json' \
  -d '{"username":"YOUR_ACCOUNT","password":"YOUR_PASSWORD"}' \
  http://localhost:8080/api/account/login
curl -b session.cookies http://localhost:8080/api/cameras
```

Use a private request file or another secure input mechanism for real secrets; the inline body above is illustrative. Protect cookie files and login responses. A programmatic client can send `Authorization: Bearer <session_token>` instead of the cookie. Sessions normally last one year; desired publications retain their owning session. Cookie/Bearer sessions, native camera settings and publication credentials survive restart in encrypted state. Explicit logout durably removes the account session and revokes its publications. Repeated valid login to the same account resumes the same workspace.

The Compose gateway supplies its own private bridge authentication automatically. When logging in directly to an API protected by `BRIDGE_ACCESS_TOKEN` or `--access-token-file`, supply that token as `Authorization: Bearer <bridge-access-token>` on the login request. It is distinct from the account session token returned by login. Media-only Basic credentials can be obtained through `GET /api/account/player`; they cannot control cameras.

## Endpoint map

All paths below are relative to the service origin. Camera IDs are opaque values returned by the current account catalog.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | API liveness, no camera/cloud check. |
| GET | `/docs/`, `/openapi.json` | Reference and machine-readable contract. |
| POST | `/api/account/login` | Create account session. |
| GET | `/api/account` | Current account summary. |
| POST | `/api/account/refresh` | Refresh own/shared camera catalog. |
| POST | `/api/account/logout` | Revoke session and close cameras. |
| GET | `/api/account/player` | Temporary media-only Basic credentials. |
| GET | `/api/cameras` | Catalog; listing does not start video. |
| GET | `/api/cameras/{camera_id}` | State, lens information and errors. |
| POST | `/api/cameras/{camera_id}/connect` | Start LAN or vendor-relay connection asynchronously. |
| POST | `/api/cameras/{camera_id}/stream` | Apply quality in place or reconnect when the route changes. |
| POST | `/api/cameras/{camera_id}/disconnect` | Close selected connection. |
| GET | `/api/cameras/{camera_id}/details` | Redacted metadata and capability evidence. |
| GET | `/api/cameras/{camera_id}/services` | Fixed native TCP service-port probes. |
| POST | `/api/cameras/{camera_id}/control` | Validated native command. |
| GET / POST | `/api/cameras/{camera_id}/export` | Read or explicitly configure bridge publication. |
| POST | `/api/cameras/{camera_id}/export/credentials` | Explicitly reveal publication-only credentials. |
| POST | `/api/exports/auth` | MediaMTX authorization callback; no account cookie required. |
| POST | `/api/cameras/{camera_id}/credentials` | Explicitly reveal native camera credentials; sensitive. |
| GET | `/api/cameras/{camera_id}/snapshot.jpg` | JPEG snapshot. |
| GET | `/api/cameras/{camera_id}/mjpeg` | MJPEG stream. |
| GET | `/api/cameras/{camera_id}/stream.h264` | Original H.264 stream. |

Send `{}` for POST operations without other parameters. JSON requests have an 8192-byte body limit. Host and same-origin checks apply; this is not a permissive cross-origin API.

## Connect and read video

Replace `CAMERA_ID` with a catalog ID:

```sh
curl -b session.cookies -H 'Content-Type: application/json' \
  -d '{"quality":"medium","substream":1}' \
  http://localhost:8080/api/cameras/CAMERA_ID/connect
curl -b session.cookies http://localhost:8080/api/cameras/CAMERA_ID
```

A `202` response means connection was scheduled. Poll until `viewable` is `true` or an error appears. `connection_mode` accepts `lan` (the default for `/connect`) or `cloud`:

- `lan`: optional `ip` specifies a private IPv4 address; otherwise the bridge keeps the saved LAN hint, then uses the account LAN address or UID discovery.
- `cloud`: resolve the camera UID through the vendor directory and require a relay session. No camera IP or LAN discovery is needed. An existing LAN address is retained as a hint for later local use, not replaced with a relay address. This mode does not silently fall back to LAN.

For example:

```sh
curl -b session.cookies -H 'Content-Type: application/json' \
  -d '{"connection_mode":"cloud","quality":"low","substream":1}' \
  http://localhost:8080/api/cameras/CAMERA_ID/connect
```

The catalog reports the selected `connection_mode`; `transport.mode` and `transport.path` describe the transport, with `path: relay` only after a relay connection is established. The status does not expose relay endpoint addresses or transport credentials. Source selection is saved for restart recovery. Relay negotiation may take about a minute, with up to 100 seconds allowed for the first frame; availability depends on the camera, firmware, vendor service and both networks. VP transport is unsupported.

The `substream` selector accepts `0`, `1` or `2`. The independent `quality` selector accepts `high`, `medium`, `low` or `null`; null leaves camera quality unchanged. Native quality codes are 1, 2 and 4 respectively.

Media routes accept `?lens=0` through `?lens=15`; choose lenses actually observed for the camera. Multiple lenses share one physical connection. Browser MJPEG is capped at 960 pixels wide and 5 fps. H.264 is not transcoded and may require an external player. A missing first frame returns `503`.

## Bridge RTSP / ONVIF publication

See [bridge exports](bridge-exports.md) for setup and client examples. These endpoints publish existing camera H.264 through the bridge; they do not modify native camera ONVIF/RTSP settings.

`GET /api/cameras/{camera_id}/export` returns availability, enabled state, per-observed-lens profiles and credential-free RTSP/ONVIF addresses. Enable with `POST` and `{"enabled":true,"rtsp":true,"onvif":true}`; optional `advertise_host` is a client-reachable host name or IPv4 address, without a scheme or port. Use `onvif:false` for RTSP only; ONVIF requires RTSP. Enabling requires a connected camera and a reachable MediaMTX listener. Reapplying configuration or switching the source connection retains the publication ID and credentials; source switching pauses video while the camera reconnects. Disable with `{"enabled":false}`.

An omitted `advertise_host` retains the saved publication host. For a new cloud camera, it uses the dashboard/API request host without the web port; no camera LAN IP or route to that camera is needed. Only the authenticated gateway's forwarded host is trusted. A new LAN publication retains interface inference toward the camera. Set `advertise_host` explicitly for a different NVR route or when accessing the API through localhost; otherwise the latter returns `advertise_host_required`.

`POST /api/cameras/{camera_id}/export/credentials` with `{}` reveals `username` (`bridge`) and a generated publication password. Ordinary status responses and URLs contain no password. These credentials are separate from account, camera and browser-player credentials. Logout, disconnect or disabling stops publication. API restart automatically restores it with the same paths/password.

`POST /api/exports/auth` accepts the MediaMTX HTTP-auth JSON fields `protocol`, `path`, `user`, `password` and `action`. It is an authorization decision only: no account login/cookie or session creation. Only `protocol:"rtsp"` and an exact active `<export_id>/lens<N>` path for an observed lens are eligible. The internal `publish` role can only `publish`; publication user `bridge` can only `read`. Cross-role actions, unknown paths and revoked credentials fail. Keep this callback reachable by MediaMTX, not as a client login endpoint.

## Native controls

Controls require a connected, viewable camera and execute serially in its existing session.

```sh
curl -b session.cookies -H 'Content-Type: application/json' \
  -d '{"action":"ptz_step","args":{"direction":"left"}}' \
  http://localhost:8080/api/cameras/CAMERA_ID/control
curl -b session.cookies -H 'Content-Type: application/json' \
  -d '{"action":"query","args":{"section":"parameters"}}' \
  http://localhost:8080/api/cameras/CAMERA_ID/control
```

Actions include PTZ pulses and steps, stop, calibration, cruise, presets, guard position, volume settings, image settings, zoom, light, siren, tracking, indicator, OSD and recording settings. Support varies with firmware. Volume settings do not implement audio streaming. Native archive metadata queries are separate from the bridge archive routes below.

Responses distinguish `confirmed` (firmware result 0), `rejected` (firmware rejection), `sent` (transport delivery only) and responses without a definitive result. Transport acknowledgement alone does not confirm the requested effect. Timed-out queued commands do not execute later. The expert `native` action accepts a bounded relative CGI path; the bridge inserts authentication and rejects credential overrides. It can change persistent settings.

### Explicit external-user password configuration

Only call `plaintext_password` when you intend to change the camera's native external-access settings:

```json
{"action":"plaintext_password","args":{"enabled":true,"password":"YOUR_NEW_LOCAL_PASSWORD"}}
```

The password must contain 8–63 printable non-space ASCII characters. The action uses documented `set_users.cgi` fields `ExUser=admin`, `ExPwd` and `ExUserSwitch`; disabling uses `{"action":"plaintext_password","args":{"enabled":false}}` without requiring a password. A confirmed response triggers read-back checks of `ExUserSwitch` and the presence of `WebPwd`. Returned verification contains booleans, never the password. Account-issued native credentials may differ from these external-user credentials.

This does **not** enable or verify an independent RTSP/ONVIF daemon. The dashboard's separate service toggles are disabled because those switches are not verified. `GET .../services` makes bounded TCP connection checks to ports `554`, `10554`, `10555`, `10556` and `10080` on the selected private camera address. It is not a subnet scan, protocol handshake or authentication test; `protocol_verified` remains false. Capability flags describe reported support, not running services.

Protocol references: [VStarcam CGI command list](https://shop.vstarcam.cn/docs/cgi-command-list/), [VeeSky RTSP documentation](https://open.veesky.com/docs/open-rtsp/), [published VSDK package](https://pub.dev/packages/vsdk). These describe protocol behavior; they are not a guarantee for every camera model.

## Errors

Failures return a JSON `error` code. Common statuses: `400` invalid input or camera not streaming, `401` authentication required, `403` rejected host/origin, `404` unknown route/camera, `409` connection already in progress, `415` JSON required, `502` vendor failure, and `503` no frame available. Consult the current OpenAPI contract and camera state for details. Keep native credentials, account tokens and media credentials out of URLs, issue reports and logs.


## Bridge archives

All routes require the owning account cookie or Bearer session; browser-player credentials are insufficient. Enable bridge publication before recording, SD access or RTSP replay. Completed file downloads/status remain account-accessible after reconnecting to the same account even if publication is off.

- `GET /api/cameras/{id}/archive`: recording worker state, completed records, storage policy/usage and current session import jobs. Public metadata contains no filesystem paths or passwords.
- `POST /api/cameras/{id}/archive` with `{"action":"record","enabled":true,"segment_seconds":60,"retention_days":7,"max_bytes":10737418240}` starts per-observed-lens recording. Use `{"action":"record","enabled":false}` to finalize and stop.
- `GET /api/cameras/{id}/archive/sd_dates`: available camera dates.
- `GET /api/cameras/{id}/archive/sd_records?date=YYYYMMDD`: bounded SD index; use a returned `id` rather than constructing a filename.
- `POST /api/cameras/{id}/archive` with `{"action":"sd_import","source_id":"RETURNED_ID","duration":60}` returns a job (HTTP 202). Poll archive status until completed/error/cancelled. Duration is 1–300 seconds. The selected date must first be listed within this account session.
- `GET /api/cameras/{id}/archive/file/{token}`: authenticated MKV download. Supports a single `Range: bytes=START-END` or `bytes=START-` request (206); unsupported/invalid ranges return 416.
- `POST /api/cameras/{id}/archive` with `{"action":"replay","token":"RECORDING_TOKEN"}` returns a credential-free RTSP URI for normal forward clip replay. Use the publication credentials displayed in the dashboard in the player.

The full constraints and lifecycle are described in [bridge exports](bridge-exports.md#server-and-sd-archives). SD cache and server files are separate sources in metadata, but both are exposed to ONVIF Recording/Search/Replay once complete. Recording settings are bridge storage policy; they do not change the camera SD recording configuration.


## Live quality switching

`POST /api/cameras/{camera_id}/stream` accepts the same `ip`, `substream`, `quality` and optional `connection_mode` preferences as connect. Omitted `connection_mode` retains the current mode. When the camera is connected and its mode/substream and applicable LAN IP are unchanged, it sends the native `camera_control.cgi?param=16` command through the current serialized session and returns `mode: live`. The camera/publication is retained and the preference is persisted. All lenses share the native quality. A brief encoder/keyframe transition can occur; the UI does not perform a fresh login or transport handshake.

Changing connection mode, LAN IP or substream, or applying settings to a disconnected camera, returns `mode: reconnect` and starts the usual asynchronous connection. In cloud mode a LAN-IP hint does not change the relay route. Explicit `/connect` remains a full reconnect. Null quality leaves the current native quality untouched and clears its restart override.
