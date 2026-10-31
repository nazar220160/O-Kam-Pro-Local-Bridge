# Security

This bridge handles account credentials, native camera passwords, live video and commands that can change persistent camera settings. Run it on a trusted machine and private network.

## Deployment boundaries

- Default Compose listeners are loopback-only. The web gateway keeps its generated token in a shared named volume and injects it server-side.
- Account sessions are in memory, expire after 12 hours, and are revoked on logout or restart. Browser cookies are HttpOnly and SameSite=Strict. API and media credentials are secrets too.
- The bundled HTTP listeners do not provide TLS. Use HTTPS termination or a trusted VPN for access across untrusted networks; do not expose the bridge directly to the public internet.
- The account workflow contacts vendor HTTPS services for login/catalog and transport bootstrap. Video transport requires local or routed private camera reachability.
- Metadata responses redact secret-looking fields, but review any exported diagnostic material before sharing. The explicit credentials endpoint intentionally reveals native camera credentials to the authenticated account session.
- A user-supplied legacy `SuperIPCam.exe` is inspected as data only. Do not commit it, extracted keys, secret captures or cached private camera configurations.
- Capability flags and open TCP ports do not establish protocol security or prove ONVIF/RTSP availability. Password configuration is an explicit native camera mutation, not a protocol verification step.

## Report a vulnerability

Use [GitHub's private vulnerability reporting](https://github.com/nazar220160/O-Kam-Pro-Local-Bridge/security/advisories/new) if enabled. If it is unavailable, open a minimal public issue asking the maintainer for a private contact method; omit exploit details and all secrets until a private channel is established.

Include the affected version, deployment mode, impact and a minimal redacted reproduction. Do not attach real account passwords, session cookies, gateway tokens, camera identifiers or private footage. No response-time or long-term security-support guarantee is made; use the latest release and review the [changelog](CHANGELOG.md).
