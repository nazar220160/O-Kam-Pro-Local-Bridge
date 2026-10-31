# Security

This bridge handles account credentials, native camera passwords, live video, persisted recordings and commands that can change persistent camera settings. Run it on a trusted machine and private network.

## Deployment boundaries

- The default dashboard listener is LAN-accessible; the API remains loopback-only; optional publication listeners use their separately configured RTSP_LISTEN/ONVIF_LISTEN addresses (LAN interfaces by default). The web gateway keeps its generated token in a shared named volume and injects it server-side.
- Account sessions and necessary native transport credentials are persisted as an AES-256-GCM authenticated encrypted snapshot. The vendor protocol password digest (a password-equivalent credential), vendor login token and publication passwords are included for unattended recovery; the original account password is not stored. Default browser/session lifetime is one year, with enabled publications retaining their session while desired, including temporary camera outages. Restart restores the session; explicit logout durably removes it. Browser cookies are HttpOnly and SameSite=Strict. API and media credentials are secrets too.
- The bundled HTTP listeners do not provide TLS. Use HTTPS termination or a trusted VPN for access across untrusted networks; do not expose the bridge directly to the public internet.
- The account workflow contacts vendor HTTPS services for login/catalog and transport bootstrap. Video transport requires local or routed private camera reachability.
- Metadata responses redact secret-looking fields, but review any exported diagnostic material before sharing. The explicit credentials endpoint intentionally reveals native camera credentials to the authenticated account session.
- Camera credential decoding uses a fixed protocol salt bundled for interoperability. This is not a user password; decoding still requires an encrypted record from an authenticated account. Actual account/camera passwords, secret captures and cached private configurations must not be committed. An optional legacy client-file override is inspected as data only and is not needed by standard deployments.
- Capability flags and open TCP ports do not establish protocol security or prove ONVIF/RTSP availability. Password configuration is an explicit native camera mutation, not a protocol verification step.

## Bridge publication credentials

Optional RTSP/ONVIF publication has its own generated password, retrieved through a separate authenticated POST and displayed automatically in plaintext in the selected publication panel. It is separate from camera, account and browser-player credentials. Shared addresses contain no embedded password. Treat the revealed value as a secret and enter it in the player/NVR’s separate credential fields.

MediaMTX uses a separate internal publisher credential and asks the API to authorize exact publication paths and read/publish roles. RTSP uses TCP with Basic authentication; the ONVIF facade and snapshots are also sensitive LAN services. Keep them on a trusted LAN or VPN; retain HTTPS protection for dashboard/API access. They do not inherit browser authentication.

Closing a tab keeps a publication running. API/container restart restores its ID/password and configured camera automatically. Logout removes the stored session and revokes access; disconnect and explicit disable stop publication and persist that choice. The lazy ONVIF listener may remain bound after disable, returning 404 for absent publications until restart. Bridge publication does not change the camera’s native ONVIF/RTSP configuration.

## Report a vulnerability

Use [GitHub's private vulnerability reporting](https://github.com/nazar220160/O-Kam-Pro-Local-Bridge/security/advisories/new) if enabled. If it is unavailable, open a minimal public issue asking the maintainer for a private contact method; omit exploit details and all secrets until a private channel is established.

Include the affected version, deployment mode, impact and a minimal redacted reproduction. Do not attach real account passwords, session cookies, gateway tokens, camera identifiers or private footage. No response-time or long-term security-support guarantee is made; use the latest release and review the [changelog](CHANGELOG.md).


## Recordings and ONVIF control

ONVIF publication credentials authorize supported PTZ/preset writes as well as live video, events and retained recordings for that publication. Share them only with trusted clients. Movement has a bounded watchdog; this does not make an untrusted control client safe.

The private recordings directory contains a SQLite manifest and unencrypted video. Directories/files use restricted permissions, records are scoped by stable account and camera identity, and API downloads require an account session. Player-only credentials do not grant archive downloads. MediaMTX replay authorization checks the exact registered publication/clip and uses the current publication credential. Logout/off revokes network publication and stops workers, while completed footage remains on disk for later account access and retention cleanup. Enabled server recording resumes after a restart; a deliberately stopped recorder does not. Protect backups and the recordings volume; deleting a session does not erase footage.

SD import reads camera files without deleting or formatting the card. Avoid sharing diagnostics with SD indexes, filenames or recorded images. Storage limits are per camera and active files require headroom; monitor total disk usage.


## Persistent state storage

Linux Compose mounts a private `state` named volume at `/state`. Native API defaults to `.runtime/state`; `BRIDGE_STATE_DIR` overrides it. `state.key` and `sessions.enc` have mode 0600 inside a mode-0700 directory. Writes use authenticated encryption, an atomic replacement and fsync. This protects against accidental plaintext exposure and partial writes, not an attacker who can read both the encryption key and ciphertext on the trusted host. Treat the entire volume and backups as credentials. Never commit or share them.

Back up both files together while the API is stopped. A missing key or invalid ciphertext fails closed rather than silently replacing existing sessions. `docker compose down -v` deletes state and recordings; ordinary `down` or `restart` preserves them. Expired inactive sessions are not restored. Enabled publications retain their session so an overnight camera outage does not erase NVR configuration. Explicit logout is the durable way to remove a saved account.
