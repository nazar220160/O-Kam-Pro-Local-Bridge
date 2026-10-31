"""Generate the private gateway token once; never print it."""

import os
from pathlib import Path
import secrets

root = Path("/run/bridge")
root.mkdir(parents=True, exist_ok=True)
path = root / "gateway-token"
if not path.exists():
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    with os.fdopen(fd, "w") as out:
        out.write(secrets.token_urlsafe(48))
if len(path.read_text().strip()) < 32:
    raise SystemExit(
        "Invalid gateway token; remove the private gateway volume and restart."
    )
print("Private API gateway initialized.")
