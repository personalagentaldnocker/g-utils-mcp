#!/usr/bin/env bash
set -euo pipefail
: "${1:?Usage: bash scripts/verify_image.sh IMAGE_DIGEST}"
docker run --rm --entrypoint python "$1" -c '
from pathlib import Path
import os
import subprocess
import g_utils_mcp
from starlette.testclient import TestClient
from g_utils_mcp.app import create_app
from g_utils_mcp.config import Settings
from g_utils_mcp.policy.store import PolicyStore
from g_utils_mcp.storage import MemoryStore
from g_utils_mcp.artifacts import Artifacts
root = Path("/app")
assert os.getuid() == 10001
assert not any((root / p).exists() for p in ("scripts", "infrastructure", ".git", "local", "secrets"))
assert (Path(g_utils_mcp.__file__).parent / "discovery/gmail.v1.json").is_file()
subprocess.run(["g-utils-mcp", "--help"], check=True, stdout=subprocess.DEVNULL)
store = MemoryStore()
store.put("policy", b"policy_revision: image-smoke")
app = create_app(Settings(), policies=PolicyStore(store, "policy"), secrets=object(),
                 artifacts=Artifacts(MemoryStore()), clients=object())
with TestClient(app) as client:
    assert client.get("/healthz").status_code == 200
    assert client.post("/mcp").status_code == 401
print("Non-root runtime, CLI, health, mandatory authentication and image contents verified.")
'
