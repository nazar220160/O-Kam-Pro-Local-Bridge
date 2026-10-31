# Bridge RTSP and ONVIF exports

Bridge publication lets a VLC or NVR client consume an already connected camera even when the camera has no usable native RTSP/ONVIF service. It does not change native camera settings.

RTSP runs through separate MediaMTX 1.21.2 over TCP, normally on port 8554. FFmpeg copies H.264 without encoding; audio is not published. The optional bridge ONVIF facade exposes Device/Media operations, per-observed-lens profiles, authenticated JPEG snapshots, bounded PTZ, PullPoint events and completed-clip Recording/Search/Replay services, normally on port 8899. WS-Discovery is best effort when LAN multicast works.

Camera encoder configuration writes, absolute/relative PTZ positioning, ONVIF recording-job creation, reverse playback and RTSP clock seeking are unsupported. Full ONVIF certification is not claimed. Compatibility depends on the client; profiles describe observed lenses rather than independently configurable high/low encoders. Some metadata has fallback values until the camera reports it. Do not treat successful enablement as proof of VLC/NVR compatibility.

## Enable from the dashboard

1. Start the [Linux Compose deployment or macOS launcher](deployment.md). Both include MediaMTX; the native API command alone does not start it.
2. Sign in, connect the camera and wait for live video and the desired lenses to appear.
3. Open **ONVIF / RTSP → ONVIF / RTSP от моста**. Leave RTSP selected; select ONVIF if needed.
4. Optionally enter the bridge's LAN host name or IPv4 address reachable by the player. Omit the scheme and port. Automatic selection uses the interface toward the camera; override it if your NVR uses a different route.
5. Click **Включить / применить**. Copy the returned device address or the RTSP address for the required lens.
6. Click **Показать данные входа моста** only when ready to configure your client. Enter that generated username/password separately in the client.

Ordinary status and copied addresses contain no embedded password. Publication credentials are not the camera password, O-Kam account credentials or browser-player credentials. Reapplying configuration replaces the publication ID and credentials; update clients afterwards.

## VLC and NVR setup

For VLC, open the returned RTSP address as a network stream. It has this shape:

```text
rtsp://BRIDGE_HOST:8554/EXPORT_ID/lens0
```

Enter username `bridge` and the revealed publication password when prompted. Select RTSP over TCP in the client if it offers a transport choice. Use each returned lens address for a separate view; do not invent lens IDs or reuse an address after re-enabling.

For an ONVIF NVR, try discovery on the same LAN. If the device is not found, add it manually with the returned device-service URI:

```text
http://BRIDGE_HOST:8899/onvif/EXPORT_ID/device_service
```

Provide the same publication credentials in separate fields. An NVR that only accepts a host and port must also support the publication-specific device-service path; otherwise use its generic RTSP input. Select the observed-lens profile you need. A discovery result does not guarantee the NVR implements this limited facade. Authenticated snapshots are returned through the facade's snapshot URI; they do not use your browser cookie.

## Ports and networking

Optional `.env` configuration:

```dotenv
RTSP_LISTEN=0.0.0.0
RTSP_PORT=8554
ONVIF_LISTEN=0.0.0.0
ONVIF_PORT=8899
```

Defaults allow the publication listeners to be reached through LAN interfaces. Restrict them to your intended interface if necessary. `WEB_LISTEN` controls the dashboard independently. Allow RTSP TCP 8554 and ONVIF TCP 8899 from your player/NVR; best-effort WS-Discovery uses IPv4 multicast `239.255.255.250` on UDP 3702. Use a trusted LAN or VPN for these services and the existing HTTPS guidance for dashboard/API access.

On Linux, the default deployment uses host networking. On macOS, `./start-macos.sh` keeps camera UDP handling native and runs the dashboard plus MediaMTX in Docker. The all-container Docker Desktop setup is experimental: multicast discovery generally cannot cross NAT, and camera UDP reachability is not guaranteed. Use a manual ONVIF URI when discovery fails.

A custom native deployment uses `BRIDGE_RTSP_INTERNAL_URL` for the API-to-MediaMTX upstream and `BRIDGE_RTSP_PORT` for the public advertised RTSP port. `BRIDGE_ONVIF_LISTEN` and `BRIDGE_ONVIF_PORT` configure the API-owned ONVIF listener. Internal and public addresses may differ; the advertised host must be reachable by the NVR.

## Lifecycle and diagnostics

Enabled publication keeps its owning account session exempt from the normal 12-hour TTL and extends its browser cookie to one year. Closing the tab does not stop video. All publication state and passwords remain in RAM: logout, camera disconnect, explicit **Выключить экспорт**, or API restart revokes publication. After restart, sign in, reconnect and enable again. Cookie longevity does not restore lost server state.

The ONVIF listener opens lazily on the first ONVIF enable. It remains bound until server restart even after all publications are disabled; missing or revoked publication paths return 404. RTSP authorization rejects revoked publication paths and credentials.

`rtsp_service_unavailable` means the configured MediaMTX listener is unreachable; check that service and its internal URL/port. `onvif_port_unavailable` means the API could not bind the ONVIF listener. A publication can remain in `starting` until H.264 frames arrive. Check the export status, observed lenses and MediaMTX/API logs; redact identifiers and secrets before sharing diagnostics. A `discovery_error` does not prevent manual ONVIF setup when the HTTP endpoint is reachable.

For HTTP configuration, credential reveal and MediaMTX callback details, see the [API guide](api.md).


## PTZ and events

PTZ is advertised only when the connected camera reports a motor. ContinuousMove maps normalized pan/tilt velocity to short serialized native pulses. Every move has a watchdog (maximum five seconds); Stop cancels the move and sends a native stop. GetStatus reports movement without inventing absolute coordinates. Native preset slots 1–5 are read and changed only through confirmed camera responses. Unsupported movement spaces and zoom return SOAP faults.

PullPoint subscriptions support topic filters, synchronization, renewal and unsubscribe. The bridge polls actual native state approximately every two seconds. Generic alarm notifications preserve the raw firmware value; they do not claim its meaning. Motion notifications are generated only when firmware supplies an explicit recognized motion-state field. This camera may therefore expose raw alarms without motion notifications. There is no inferred video analytics or historical event persistence. Subscriptions are bounded, expire and are revoked with publication.

## Server and SD archives

In the same dashboard service tab, use the separate archive panel:

1. Enable bridge publication first. Server recording and SD import are off by default.
2. For server recording, choose segment duration (5–3600 seconds), retention (1–365 days) and the camera storage quota (1 MiB–1 TiB). Defaults are 60 seconds, seven days and 10 GiB. Start recording explicitly. Each observed lens is stored separately as H.264 copied into Matroska; only completed, probeable files enter the manifest. A final partial segment is finalized on stop where possible.
3. For SD, load available dates, list the chosen date and import a selected clip (1–300 seconds). The bridge reads the camera index and downloads into its private cache through a separate authenticated native session. It never formats the card or deletes camera files. Multi-lens clips become separate cached records. Firmware compatibility is required, and another camera session or poor connection can interrupt import.
4. Download a completed MKV or request its replay address. Browser MKV playback depends on browser/codec support; use VLC when necessary. Replay uses the current publication credentials and RTSP/TCP.

ONVIF Recording/Search enumerates completed server recordings and imported SD cache files. Uncached SD entries must first be listed/imported through the dashboard or HTTP API; they are not advertised as playable ONVIF records. Each clip/lens is a separate recording token. GetReplayUri starts ordinary forward playback from the clip beginning. A new request for the same clip restarts its publisher. These services do not implement a continuous Profile G timeline or reverse/seek semantics.

Recordings persist across logout/restart, scoped by account and camera; publication credentials, recording workers, subscriptions and replay processes do not. Sign in again to access retained files, reconnect and re-enable publication for ONVIF replay. Recording does not automatically resume after restart. Age retention applies to server recordings; imported SD clips keep their original timestamps and are not deleted merely because the source is old. Both sources share the camera quota, evicted oldest first when a new file is added. Limits are enforced at completion/import, so active segments/imports need additional free disk space. SD import requires at least 2 GiB free, with at most two active imports globally. These are per-camera limits, not a global disk reservation.

Linux Compose stores the private SQLite manifest and clips in the `recordings` named volume. The native macOS default is `.runtime/recordings`; override with `BRIDGE_RECORDINGS_DIR`. Back up/protect this directory as private footage. `docker compose down -v` deletes named-volume recordings. Explicit logout/off/disconnect stops active recording and replay but preserves completed files.
