# Changelog

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
