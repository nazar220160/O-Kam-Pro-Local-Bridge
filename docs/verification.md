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

## 0.8.0 ONVIF control, events and both archive sources

- Final macOS / Python 3.14 suite: 216 tests passed, including independent WSDL parsing. Linux arm64 / Python 3.12 runtime: 216 tests ran with networking disabled and read-only root; five optional checks skipped (three require Docker CLI, two require development-only ONVIF WSDL dependencies), all remaining tests passed. All five Node frontend suites and OpenAPI validation passed. API/web images built successfully. An isolated named-volume check verified archive writes under a read-only container root and manifest persistence after container recreation.

- Independent `onvif-zeep` client read Device capabilities, PTZ nodes/configurations/status and event properties. On the physical three-lens camera, paired short pan movements and Stop returned successfully. Preset writes were tested against controlled protocol replies, not changed on physical hardware.
- An authenticated PullPoint subscription delivered an observed native alarm notification. This establishes the raw alarm path; it does not establish the meaning of every firmware alarm code or verify a real motion transition. Motion is emitted only for explicit recognized firmware motion fields.
- Opt-in server recording produced six completed per-lens Matroska files during the live smoke run. SD enumeration returned dates and indexed clips; a selected 15-second clip was imported as three separate lens files. Direct SD driver verification probed H.264 1920×1080 and decoded frames from all three files.
- ONVIF Recording listed all nine completed files; Search returned all nine. Independent FFmpeg decoded a frame from RTSP Replay for a server file and an SD-cache file. Authenticated HTTP ranged downloads returned 206 and the requested 32 bytes for each source.
- Diagnostic recording/publication were disabled and the account logged out after the run. No SD file deletion, card formatting or native camera ONVIF/RTSP configuration change was performed. Completed diagnostic clips remain private in the ignored runtime storage, not in Git.
- Added regression coverage for subscription/search isolation and expiry, unsupported protocol operations, bounded motion/Stop, SD binary/index parsing, server remux/decode, persistent owner scoping and policy, recorder enable/disable races, explicit SD identifiers, HTTP archive authorization/ranges, safe transport errors and frontend account/camera races. WSDL response parsing uses independent packaged schemas through a development-only dependency.

These are partial ONVIF services, not certified Profiles S/T/G. No claim is made for absolute PTZ positioning, reverse or clock-seek replay, audio, every NVR implementation, every camera firmware, or cross-LAN multicast discovery.


## 0.8.1 self-contained credential decoding

- Final macOS suite: 219 tests passed. Linux arm64 / Python 3.12 runtime: 219 tests ran, six optional development/Docker-CLI checks skipped, all remaining checks passed. All five Node frontend suites and OpenAPI validation passed.

- Built-in decoding matched the former client-file decoder for two authorized cached account records. A fresh account login and physical-camera connection using LANBackend without a client-file argument authenticated and received a real video frame. No native settings were changed.
- An isolated source copy containing no `.env` or official executable built and reached healthy API/web states with fresh Docker volumes. The Docker Desktop networking override and separate test ports were used to avoid disrupting the existing deployment. Inside that container, the built-in decoder passed a synthetic known-answer vector while the external client path was absent. The temporary test stack/volumes were removed. Linux host-network Compose defaults are validated separately; this check does not claim physical camera UDP works through Docker Desktop.
- Regression coverage includes known-answer decoding with filesystem access forbidden, a stale/missing legacy override, invalid input rejection, no client-file mount in clean Compose, LAN dashboard defaults and explicit loopback restrictions. Actual user credentials and proprietary executables remain outside Git; the fixed interoperability salt is deliberately included in source.


## 0.8.2 host/port ONVIF bootstrap

- Full macOS suite: 223 tests passed; all five frontend suites and OpenAPI validation passed. Docker image rebuild was not performed because the local Docker daemon was unavailable; no new container verification is claimed for this release.

- Frigate's upstream client dependency (`onvif-zeep-async` 4.3.0) was run against the bridge with two controlled publications on one listener. Host/port bootstrap, authenticated camera selection, device information, profiles, RTSP URIs, PTZ capabilities/nodes/presets and configuration options passed for both publications. No physical movement was sent. This is a client interoperability check, not a full Frigate deployment test.
- Independent synchronous Zeep clients exercised WS-Security PasswordDigest and HTTP Digest against the standard entry point. Regression checks cover incorrect credentials, revoked publications, camera isolation and clock bootstrap without camera metadata disclosure. Existing publication-specific URLs are preserved.

## 0.9.0 live audio and Frigate wizard stability

- Real camera acknowledged ephemeral G.711 A-law receive command `audiostream.cgi?streamid=7` and delivered native type-12 audio packets. AAC audio now accompanies all three live H.264 lens RTSP publications. Video remains copied; two-way audio and audio in browser MJPEG/server/SD archive files are not implemented.
- A fixed video frame-count clock failed to track the camera's variable actual frame cadence. Capture-time input timestamps and monotonic high-resolution packet timestamps replaced it. Three simultaneous 60-second video+audio decodes inside the installed Frigate container completed in 60.4–60.7 seconds, with 384–386 video frames per lens and no decoder errors. The null-output verification preserved the stream's fine-grained time base rather than rounding variable-rate frames onto a coarse fixed-rate clock.
- Final Frigate utility checks: two rounds of three simultaneous RTSP metadata probes all passed in 0.68–0.84 seconds and reported H.264 plus AAC. Two rounds of simultaneous snapshots all passed; cold lens previews took 0.13–0.19 seconds, subsequent cached previews 0.00–0.01 seconds.
- The optional Frigate derivative image preserves the installed custom base image and changes only wizard probe/snapshot functions. Metadata probes use TCP immediately with bounded analysis. Bridge snapshot URLs use authenticated cached ONVIF JPEGs. The live JPEG decoder now retains the cached keyframe and uses bounded single-thread decoding instead of discarding the first GOP. A regression reproduced a preview timeout with an open pipe and one GOP, then passed after the fix.
- All 233 macOS Python tests, all five Node frontend suites and OpenAPI validation passed. The bridge/web images and the Frigate derivative were built on the actual Linux server. Frigate's prior Compose override/image were retained for rollback. Diagnostic account sessions and private URL/token files are excluded from Git.

These checks cover the tested camera, installed Frigate build and measured network conditions. They do not promise continuous availability during camera/network outages. An API restart still revokes in-memory publications: log in, reconnect and enable publication again, then refresh the NVR's stream addresses and credentials.

## 0.10.0 encrypted restart recovery

- New regressions cover cookie/Bearer and player token restoration, unchanged publication paths/passwords, saved camera IP/quality, pending settings overriding cached transport settings, recording policy resumption, delayed MediaMTX startup, durable off/disconnect/logout, inactive expiry, same-account re-login, state-file tampering and missing-key failures.
- On the actual Linux server, the existing authorized Frigate publication ID/password were migrated into encrypted state without changing Frigate's source configuration. All three old RTSP lens URLs again returned H.264 and AAC.
- A real API-container restart and a forced container recreation with the named state volume retained the same browser cookie, player token, publication ID/password and camera preferences. The API accepted the unchanged cookie, reconnected the physical camera and restored ONVIF/RTSP automatically. Independent Frigate probes read all three old lens URLs after both operations. During cold publisher startup an immediate probe can see a transient not-ready response; retrying while restoration completes succeeded without any NVR configuration change.
- Linux uses a dedicated mode-0700 `/state` volume; key/ciphertext files are mode 0600. Atomic authenticated encryption protects state integrity and interrupted writes. The original account password is not saved; the encrypted protocol digest is a credential and the volume/key must be protected together. Explicit logout is deliberately durable; verification leaves the migrated production session enabled.
