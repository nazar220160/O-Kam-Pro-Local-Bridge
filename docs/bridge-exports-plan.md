# Bridge-owned ONVIF / RTSP publication

Native camera service settings remain untouched. Add a separate per-camera publication feature that uses the existing camera session and original H.264. FFmpeg remuxes into MediaMTX RTSP/TCP without video encoding. A limited ONVIF facade advertises profiles for the actual observed lenses, stream/snapshot addresses, device metadata and supported operations; no ONVIF certification is claimed.

API: GET/POST /api/cameras/{id}/export, explicit POST /api/cameras/{id}/export/credentials, bounded MediaMTX HTTP authorization callback /api/exports/auth. Separate random publication credentials are never included in catalog/metadata/URLs. Publications keep the camera demand and owning in-memory session alive while enabled; logout, explicit disconnect and server shutdown revoke publication. Closing a browser tab does not stop it. Restart requires login/enable again.

Per-camera RTSP and ONVIF switches are independent UI actions; ONVIF relies on RTSP media. Disabled by default. Advertise host is validated or inferred from the route to the camera, configurable for NVR access. MediaMTX exposes RTSP/TCP 8554 only; API exposes ONVIF 8899 only when requested. Discovery runs on native host where possible, with manual ONVIF URL available if multicast is unavailable.

Implementation tasks:
1. Tests first for registry credential isolation, lifecycle/revocation, path auth, bounded input and source-preserving publication; implement FFmpeg publisher and export registry.
2. Independent ONVIF adapter plus local SOAP/auth/discovery tests.
3. Integrate account lifetime/close/disconnect and API routes; schema route/permissions tests. Preserve all native service operations.
4. Independent UI section with separate credentials and guarded asynchronous selection; tests for stale responses and explicit-only writes.
5. Compose MediaMTX deployment for Linux and native macOS API; update launcher, docs and generated OpenAPI.
6. Run Python/JS/schema checks, actual MediaMTX RTSP authentication/read/decode and ONVIF client against the selected camera, verify revoke; review before commit/push to existing private repository.
