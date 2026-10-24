#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
task_region="${GCP_REGION:-europe-west3}"
task_repository="$(terraform -chdir=infrastructure/foundation output -raw image_repository)"
task_tag="$(git rev-parse --short=12 HEAD)"
gcloud auth configure-docker "${task_region}-docker.pkg.dev" --quiet
docker buildx build --platform linux/amd64 --push --provenance=false \
  --tag "${task_repository}:${task_tag}" .
task_digest="$(gcloud artifacts docker images describe "${task_repository}:${task_tag}" \
  --project "$GCP_PROJECT_ID" --format='value(image_summary.digest)')"
if [[ ! "$task_digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo 'Registry did not return an immutable digest' >&2
  exit 1
fi
echo "${task_repository}@${task_digest}"
