#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Use this when Docker's own network cannot reach package registries. uv verifies
# the lockfile on the host; only the resulting virtualenv reaches the final image.
uv sync --locked --all-groups
task_uv_cache="$(uv cache dir)"
task_dockerfile="$(mktemp)"
trap 'rm -f "$task_dockerfile"' EXIT
python - "$task_dockerfile" <<'PY'
from pathlib import Path
import sys
text = Path("Dockerfile").read_text()
old = "RUN uv sync --locked --no-dev --no-editable --compile-bytecode"
assert text.count(old) == 1
text = text.replace(old, "COPY --from=uv-cache / /root/.cache/uv\nRUN uv sync --locked --offline --no-dev --no-editable --compile-bytecode")
Path(sys.argv[1]).write_text(text)
PY
docker build --build-context "uv-cache=${task_uv_cache}" -f "$task_dockerfile" \
  -t "${LOCAL_IMAGE:-g-utils:local}" .
