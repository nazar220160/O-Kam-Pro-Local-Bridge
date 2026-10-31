# Security

This bridge handles account credentials, native camera passwords, live video and commands that can change persistent camera settings. Run it on a trusted machine and private network.

## Deployment boundaries

- Default dashboard/API listeners are loopback-only; optional publication listeners use their separately configured RTSP_LISTEN/ONVIF_LISTEN addresses (LAN interfaces by default). The web gateway keeps its generated token in a shared named volume and injects it server-side.
- Account sessions are in memory and normally expire after 12 hours; an enabled bridge publication exempts its owning session from that TTL and extends its browser cookie to one year. Logout or restart still revokes the session. Browser cookies are HttpOnly and SameSite=Strict. API and media credentials are secrets too.
- The bundled HTTP listeners do not provide TLS. Use HTTPS termination or a trusted VPN for access across untrusted networks; do not expose the bridge directly to the public internet.
- The account workflow contacts vendor HTTPS services for login/catalog and transport bootstrap. Video transport requires local or routed private camera reachability.
- Metadata responses redact secret-looking fields, but review any exported diagnostic material before sharing. The explicit credentials endpoint intentionally reveals native camera credentials to the authenticated account session.
- A user-supplied legacy `SuperIPCam.exe` is inspected as data only. Do not commit it, extracted keys, secret captures or cached private camera configurations.
- Capability flags and open TCP ports do not establish protocol security or prove ONVIF/RTSP availability. Password configuration is an explicit native camera mutation, not a protocol verification step.

## Bridge publication credentials

Optional RTSP/ONVIF publication has its own generated password, revealed only by an explicit authenticated POST. It is separate from camera, account and browser-player credentials. Shared addresses contain no embedded password. Treat the revealed value as a secret and enter it in the player/NVR’s separate credential fields.

MediaMTX uses a separate internal publisher credential and asks the API to authorize exact publication paths and read/publish roles. RTSP uses TCP with Basic authentication; the ONVIF facade and snapshots are also sensitive LAN services. Keep them on a trusted LAN or VPN; retain HTTPS protection for dashboard/API access. They do not inherit browser authentication.

Closing a tab keeps a publication running in RAM. Logout, camera disconnect, explicit disable or API restart revokes it. Restart requires login and enable again. The lazy ONVIF listener may remain bound after disable, returning 404 for absent publications until restart. Bridge publication does not change the camera’s native ONVIF/RTSP configuration.

## Report a vulnerability

Use [GitHub's private vulnerability reporting](https://github.com/nazar220160/O-Kam-Pro-Local-Bridge/security/advisories/new) if enabled. If it is unavailable, open a minimal public issue asking the maintainer for a private contact method; omit exploit details and all secrets until a private channel is established.

Include the affected version, deployment mode, impact and a minimal redacted reproduction. Do not attach real account passwords, session cookies, gateway tokens, camera identifiers or private footage. No response-time or long-term security-support guarantee is made; use the latest release and review the [changelog](CHANGELOG.md).
