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
