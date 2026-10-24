#!/usr/bin/env bash
set -euo pipefail
: "${1:?Usage: bash scripts/verify_image.sh IMAGE_DIGEST}"
docker run --rm --entrypoint python "$1" -c '
from pathlib import Path
import google_utils_mcp
root = Path("/app")
assert not any((root / p).exists() for p in ("scripts", "infrastructure", ".git", "local", "secrets"))
assert (Path(google_utils_mcp.__file__).parent / "discovery/gmail.v1.json").is_file()
print("Runtime package and pinned discovery present; administrative directories absent.")
'
