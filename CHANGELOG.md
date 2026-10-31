# Changelog

## 0.11.0

- Add an explicit O-Kam Pro relay video button beside LAN playback. Reuse native CS2 relay negotiation and camera authorization; no LAN IP or discovery is required and there is no silent LAN fallback.
- Expose selected connection mode and actual transport path in camera status. Persist the source across restart, retain LAN hints and preserve existing RTSP/ONVIF publication IDs/passwords when switching sources.
- Keep quality changes on the current local or relay session; document relay network requirements, vendor/firmware availability limits and unsupported VP transport.

## 0.10.1

- Apply native quality changes over the existing serialized camera session. Preserve the connection, camera object, publication ID/password and persisted preferences. IP/substream changes and explicit reconnect retain their prior behavior.
- Keep browser feeds open when applying quality; document the live stream-preference endpoint.


## 0.10.0

- Persist account sessions, encrypted vendor credentials, native connection settings, camera IP/quality and publication IDs/passwords in an atomic AES-256-GCM state volume.
- Restore cameras, ONVIF/RTSP publications and enabled server recording in the background after restart; preserve NVR URLs and credentials and retry temporary outages.
- Resume the same workspace on verified login; retain browser/player tokens across restart, while explicit logout/off/disconnect remains durable.
- Remember selected camera/tab in browser preferences. Add the private state volume automatically to Compose.


## 0.9.0

- Receive supported native G.711 A-law microphone frames and publish real AAC audio with each live RTSP lens stream. Preserve video-only fallback and separate bounded audio/video queues.
- Use capture-time video/audio timestamps rather than a fixed frame-count clock, preserving variable native frame cadence; flush RTSP packets with low mux delay.
- Provide an optional Frigate derivative-image adapter for direct-TCP, bounded metadata probes and authenticated cached ONVIF snapshots below the wizard browser timeout.
- Browser streams and bridge archives remain video-only; two-way audio is not implemented.


## 0.8.2

- Support the standard `/onvif/device_service` entry point used by Frigate and other host/port clients. Select each publication by authenticated credentials while keeping subsequent service URLs scoped to that camera.
- Verify bootstrap, profiles, stream URIs and PTZ queries using Frigate's onvif-zeep-async 4.3 client; add multi-publication authentication and revocation regressions.

## 0.8.1

- Show publication username/password automatically as selectable plaintext fields; remove reveal/hide buttons and the hiding timer. Clear fields when changing account/camera or disabling publication.

- Decode supported encrypted camera credentials directly in the bridge. Remove the required official PC client and secrets mount from Compose and the macOS launcher. Keep an explicit legacy client-file override for alternate protocols.
- Make the dashboard reachable on LAN by default, while keeping the protected API on loopback. Explicit WEB_LISTEN overrides still apply.
- Update clean-start documentation and add no-file decoder/deployment regression coverage.


## 0.8.0

- Extend bridge-owned ONVIF with bounded continuous pan/tilt, Stop, native presets and truthful status, plus authenticated PullPoint subscriptions backed by observed native alarms.
- Add opt-in per-lens server recording, private persistent manifest/storage, retention and quotas.
- Add SD date/index enumeration and bounded multi-lens clip import without modifying SD files.
- Expose completed server/SD clips through authenticated ranged downloads, ONVIF Recording/Search and forward RTSP Replay. Add a separate archive panel and documented HTTP routes.
- Persist recordings in a dedicated Docker volume; preserve native camera-service controls and the native macOS UDP path.
- Absolute PTZ, reverse/clock-seek replay, audio and ONVIF certification remain unsupported.


## 0.7.0

- Add optional bridge-owned RTSP/TCP publication through the separate MediaMTX 1.21.2 service, copying H.264 without encoding.
- Add a read-only ONVIF Device/Media facade, authenticated snapshots and best-effort WS-Discovery, with profiles for observed lenses. No PTZ, events, recording facade or ONVIF certification is claimed.
- Add explicit publication credentials and exact-path MediaMTX read/publish authorization.
- Keep enabled publications running when the browser tab closes; revoke on logout, camera disconnect, disable or API restart. Publication state remains in RAM.
- Include MediaMTX in the Linux Compose deployment and native macOS launcher; retain the native macOS camera-UDP transport fix.
- Preserve existing native camera ONVIF/RTSP controls unchanged; bridge publication does not enable camera daemons.


## 0.6.1

- Fix native password selection when the account returns both plaintext external-access credentials and encrypted dual-auth credentials. Native video uses the encrypted credential and current account authorization; explicit credential reveal follows the same selection.
- Add a macOS launcher with the API on the host and the independent web panel in Docker, avoiding Docker Desktop UDP reachability failures.
- Add regression coverage for dual credentials, legacy plaintext cameras and macOS deployment isolation.


## 0.6.0

- Separate standalone Python HTTP API from the static nginx dashboard.
- Provide a self-contained API reference and OpenAPI 3.1 contract.
- Add Compose initialization of the shared private gateway token and loopback defaults.
- Support account-session cookies and Bearer tokens for API clients.
- Expose local camera video, lens and native quality selection, PTZ and validated controls.
- Provide redacted metadata, capability evidence and bounded native service-port probes.
- Add explicit external-user password configuration with redacted read-back verification.
- Document transport compatibility, deployment prerequisites and native RTSP/ONVIF limits.

Hardware behavior remains model- and firmware-dependent. This release does not add audio, two-way talk, SD playback, VP transport or a bridge-hosted RTSP server.
