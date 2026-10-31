# Contributing

Bug reports, compatibility findings, documentation improvements and focused pull requests are welcome.

## Report a problem

Open an [issue](https://github.com/nazar220160/O-Kam-Pro-Local-Bridge/issues) with the project version, operating system, Docker/native deployment, camera model and transport family if known, expected behavior and minimal reproduction steps. Include only redacted logs. Never upload account credentials, camera passwords, session tokens, camera UIDs, serial numbers, private camera footage, captures containing secrets, or proprietary client files. Use the private process in [SECURITY.md](SECURITY.md) for vulnerabilities.

Distinguish reported capability, observed transport delivery and verified camera behavior. A firmware feature flag or open TCP port alone is not proof that a service works.

## Develop locally

Use Python 3.12+, FFmpeg and Node.js for the frontend checks:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m unittest discover -s tests
node --test tests/*.test.cjs
```

The dashboard is plain HTML, CSS and JavaScript under `web/`; the API is under `okam_bridge/`. Use the [deployment guide](docs/deployment.md) to run them together. Automated tests do not establish compatibility with every physical camera.

Keep changes focused. Add meaningful regression coverage for behavior changes, update the OpenAPI contract and user docs when changing the API, and preserve inherited license notices. Do not add vendor secrets, executables or private configuration to the repository. Native commands that alter credentials or persistent camera settings must remain explicit user actions.

In a pull request, explain the problem, resulting behavior, checks you actually ran and any limits of hardware validation. Mention firmware/model differences without publishing device identifiers.
