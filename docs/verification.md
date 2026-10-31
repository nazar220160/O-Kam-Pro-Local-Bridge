# Release verification — 0.6.0

Checks performed on 2026-10-31:

- Python unit/integration suite on macOS / Python 3.14: 113 tests passed.
- Same suite inside the Linux arm64 / Python 3.12 image, with external networking disabled: 113 tests ran, one optional Docker CLI configuration check skipped because the CLI is absent from the runtime image; all remaining tests passed.
- Three Node.js frontend suites passed: account/camera selection races, native-service UI behavior, and asset/DOM consistency.
- OpenAPI 3.1 contract validated with `openapi-spec-validator` 0.7.2.
- Docker images built; API and web containers reached healthy state using the Docker Desktop override.
- HTTP smoke checks confirmed the dashboard, health endpoint, API reference and OpenAPI JSON through the nginx gateway. Unauthenticated catalog access returned 401.
- Real account login and catalog retrieval succeeded through the gateway; the video connection attempt did not produce a frame. Live camera streaming in this new Docker deployment is therefore not claimed as verified. The native diagnostic retry failed account login. These checks do not establish firmware compatibility or prove the cause of camera unavailability.
- Native ONVIF/RTSP configuration commands were not sent to physical hardware during this release. Password write/readback and redaction were checked using controlled protocol replies. TCP probes do not verify a native protocol login.
- Independent code review found a metadata-refresh reset issue; a regression test reproduced it and passed after the fix.
- Tracked source was checked for private configuration, captures, proprietary executables and known local decoder/config secrets. None were included.

The initial GitHub Actions run did not start its jobs: GitHub reported an account billing/spending-limit restriction. No hosted CI pass is claimed. The workflow is configured to repeat Python, frontend, schema and Compose checks when runners are available. A passing CI run does not establish compatibility with all physical cameras.


## 0.6.1 follow-up

The updated macOS suite passed all 120 tests. All three frontend Node suites and the OpenAPI contract validation passed again.

- Same code and camera: native macOS UDP discovery/handshake succeeded twice; Docker bridge and host networking each failed twice with no LAN reply.
- After enabling plaintext access, the account supplied both ordinary and encrypted credentials. The ordinary candidate was rejected by native authentication; decoding the account-issued security credential authenticated and produced a real H.264 frame.
- The fixed native macOS API, accessed through the Docker dashboard proxy, reached streaming and returned valid JPEG snapshots for all three lenses. The diagnostic session was logged out; no persistent camera settings were changed.
- Regressions cover encrypted credential precedence, matching explicit credential reveal, unchanged legacy plaintext-only behavior, native loopback/gateway isolation, stable runtime token, macOS Compose routing and inherited access-token environment isolation.


## 0.7.0 bridge publications

- Full Python suite: 140 tests passed on macOS and in the Linux arm64 runtime image (three Docker-CLI-dependent checks skipped in the image); four Node frontend suites passed. Added tests for publication isolation, credential reveal, role/path authentication, logout/disconnect revocation, session lifetime, enable-versus-disable races, publisher cancellation, listener restrictions, ONVIF SOAP authentication/replay protection, lens mapping and discovery.
- Real camera through the existing macOS API and Docker dashboard/MediaMTX: three authenticated RTSP/TCP streams were inspected by FFprobe, each H.264 at 1920×1080. No transcoding was used. Unauthenticated RTSP was rejected.
- Independent `onvif-zeep` client with UsernameToken PasswordDigest retrieved device capabilities, all three profiles and each RTSP stream URI. A snapshot fetched using HTTP Digest was a real JPEG.
- Disabling publication revoked its MediaMTX credentials. The diagnostic account session was logged out afterwards. Native camera service settings were not changed.
- ONVIF Device/Media is a limited read-only facade, not a certified ONVIF device. PTZ/events/recordings and arbitrary NVR compatibility are not claimed. Real multicast discovery was not verified across another LAN client.
