# ONVIF control, event and recording extension

Preserve native camera service settings and the working bridge-owned RTSP facade. Extend actual, authenticated services:

- PTZ: native motor evidence controls capability exposure. Continuous normalized pan/tilt runs short serialized pulses with a five-second watchdog, explicit Stop cancels pending pulses. Report MoveStatus without inventing absolute positions. Map native preset slots only on confirmed responses; unsupported zoom/absolute positioning faults.
- Events: actual native status polling feeds bounded PullPoint subscriptions, TTL, filters, synchronization, renewal and unsubscribe. Preserve unknown/raw alarm states and emit motion only for explicit motion state fields. No video-based inferred events.
- Server archive: explicit opt-in recording to persistent per-account/camera storage, H264 copy segments, manifest and retention/quota. Completed valid files only become searchable and replayable.
- SD archive: separate authorized native session, bounded date/index parser, explicit download/cache job using the verified timeline playback channel and framing. Never delete or format SD files. Multi-lens SD frames become per-lens playable cache entries.
- ONVIF Recording/Search/Replay exposes actual playable server/cache files and normal forward RTSP playback. Uncached SD entries are enumerated/imported through API, then appear in searchable replay. Do not claim reverse/absolute live PTZ or certified Profile G.
- UI/API: show source, recording status, quota, dates, SD import progress and actual file playback. Keep credentials scoped to current publication; revoke access on logout/off/disconnect. Files remain private on disk until retention cleanup.

Verification evidence and remaining hardware/client limitations are recorded in [verification.md](verification.md).
