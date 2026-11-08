#!/usr/bin/env bash
set -euo pipefail
: "${1:?Usage: bash scripts/verify_image.sh IMAGE_DIGEST}"
docker run --rm --entrypoint python "$1" -c '
from pathlib import Path
import os
import subprocess
from starlette.testclient import TestClient
from g_utils_mcp.app import create_app
root = Path("/app")
assert os.getuid() == 10001
assert not any((root / p).exists() for p in ("scripts", "infrastructure", ".git", "local", "secrets"))
subprocess.run(["g-utils-mcp", "--help"], check=True, stdout=subprocess.DEVNULL)
empty = {"version": 2, "principals": {}, "accounts": {}, "grants": {}}
with TestClient(create_app(lambda: (empty, 1))) as client:
    assert client.get("/healthz").status_code == 200
    assert client.post("/mcp").status_code == 401
print("Non-root runtime, CLI, health, mandatory authentication and image contents verified.")
'
