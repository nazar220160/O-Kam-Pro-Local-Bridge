# Public bridge architecture

Two independently runnable services: a Python LAN camera API and a static web application behind an nginx reverse proxy. API routes retain existing account, camera, controls and media contracts; session Bearer authentication is added for standalone API clients. OpenAPI 3.1 documents every route, inputs, errors and authentication. No HTML dashboard is bundled in the Python package.

Docker Compose on Linux uses host networking for the bridge, listening on loopback 8099. Web is a separate nginx service on loopback 8100 by default, proxies API/media without buffering and preserves public origin validation. Shared randomly generated gateway credentials protect the private API and are never shipped in source. An optional official-client file is user-supplied and excluded from Git/images. Browser account secrets remain memory-only. Cameras still require LAN/routed access; this does not add WAN transport.

Native services: inspect reported support and separately probe known TCP ports; only verified native write commands become toggles. Never treat support flags or transport ACKs as success. Unsupported ONVIF/RTSP enable remains explicit, with the official plaintext-password workflow described. Changes occur only after a user submits a setting; no camera setting changes during automated tests.

Panel: responsive camera workspace, clear live/idle/error states, lens grid, settings groups, PTZ, service diagnostics, API links and accessible keyboard navigation. Preserve current camera capabilities and race protections.

Public project: MIT license plus third-party notices, English README with Russian guide, Compose instructions, API examples, security/contribution notes, CI and tests. Publish only sanitized source to the explicitly requested empty repository.
