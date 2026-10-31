# Contributing

Bug reports, compatibility findings, documentation improvements and focused pull requests are welcome.

## Report a problem

Open an [issue](https://github.com/nazar220160/O-Kam-Pro-Local-Bridge/issues) with the project version, operating system, Docker/native deployment, camera model and transport family if known, expected behavior and minimal reproduction steps. Include only redacted logs. Never upload account credentials, camera passwords, session tokens, camera UIDs, serial numbers, private camera footage, captures containing secrets, or proprietary client files. Use the private process in [SECURITY.md](SECURITY.md) for vulnerabilities.

Distinguish reported capability, observed transport delivery and verified camera behavior. A firmware feature flag or open TCP port alone is not proof that a service works.

## Develop locally

Use Python 3.12+, FFmpeg and Node.js 22+:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m unittest discover -s tests
```

The independent Python API is under `okam_bridge/`. The frontend is a Next.js App Router application under `web/src/`, written in TypeScript with shadcn/ui and Tailwind CSS. TanStack Query owns server state and cache invalidation; Axios handles the same-origin API. Follow existing query keys and account-switch cleanup when adding requests.

Install and check the frontend using its committed lockfile:

```sh
cd web
npm ci
npm run typecheck
npm run lint
npm test
node --test scripts/csp-check.mjs
node --test scripts/dev-check.mjs
npm run build
```

`npm run build` exports `web/out/` and derives a CSP hash list from the generated inline scripts. The production nginx image serves those files and proxies the existing API. Do not put account passwords, gateway tokens or session tokens in public environment variables, build output or persistent query caches.

For live development, first start the bridge with its nginx gateway using the [deployment guide](docs/deployment.md), then run `BRIDGE_DEV_URL=http://127.0.0.1:8080 npm run dev` from `web/` and open `http://localhost:3000`. Point `BRIDGE_DEV_URL` to the gateway, not the protected Python API port. The local development proxy forwards API/media traffic and normalizes the upstream Origin/Host while the existing gateway supplies its private token. It does not change production CORS or authentication.

The proxy binds to `127.0.0.1:3000`; Next.js listens internally on `127.0.0.1:3001`. Optional `DEV_PORT` and `NEXT_DEV_PORT` override those ports. `DEV_HOST` explicitly changes the proxy bind address. Browser origins are checked before forwarding. Stopping the development command also stops its Next.js child and open preview streams.

Build artifacts (`.next/`, `out/`), dependencies and private runtime data do not belong in Git. Automated checks do not establish compatibility with every physical camera.

Keep changes focused. Add meaningful regression coverage for behavior changes, update the OpenAPI contract and user docs when changing the API, and preserve inherited license notices. Do not add vendor secrets, executables or private configuration to the repository. Native commands that alter credentials or persistent camera settings must remain explicit user actions.

In a pull request, explain the problem, resulting behavior, checks you actually ran and any limits of hardware validation. Mention firmware/model differences without publishing device identifiers.
