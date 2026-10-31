# Public bridge implementation plan

Goal: separate API and dashboard, document the API and package a reproducible public Docker project.

1. API tests first: headless root, OpenAPI route coverage, session Bearer login/logout, private gateway, origin and media isolation. Implement standalone API and schema/docs.
2. Native service tests first: safe read-only probes and verified service-setting actions. Preserve refusal/unsupported statuses and never mutate real hardware during automated checks.
3. Move frontend assets to web/; redesign dashboard while preserving account/camera/lens/control contracts and selection race protection.
4. Compose: bootstrap private random gateway token, host-network LAN bridge, independently built nginx dashboard, health checks and read-only containers. Verify build, start, proxied HTTP/login/docs and streaming behavior.
5. Public docs/license/CI. Run full Python and JS suites, validate API schema and secret scan all tracked source. Independent review, fix material issues, commit and push main to requested repository.

Review focus: proxy origin handling, stale account/camera async responses, session secrets in metadata or docs, false native-service support claims, Docker Desktop LAN limitations.
