#!/usr/bin/env bash
# Build the runtime image and push it to the foundation Artifact Registry repository.
# BUILDER=docker (default) builds locally with buildx; BUILDER=cloudbuild builds
# remotely with Cloud Build (no local Docker needed). Prints repository@sha256:digest.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
task_region="${GCP_REGION:-europe-west3}"
task_builder="${BUILDER:-docker}"
task_repository="$(terraform -chdir=infrastructure/foundation output -raw image_repository)"
task_tag="$(git rev-parse --short=12 HEAD)"
case "$task_builder" in
  docker)
    gcloud auth configure-docker "${task_region}-docker.pkg.dev" --quiet
    docker buildx build --platform linux/amd64 --push --provenance=false \
      --tag "${task_repository}:${task_tag}" .
    ;;
  cloudbuild)
    # Uploads the checkout filtered by .gcloudignore; Dockerfile/.dockerignore apply.
    gcloud builds submit --project "$GCP_PROJECT_ID" --region "$task_region" \
      --tag "${task_repository}:${task_tag}" .
    ;;
  *)
    echo "Unknown BUILDER '${task_builder}' (use docker or cloudbuild)" >&2
    exit 1
    ;;
esac
task_digest="$(gcloud artifacts docker images describe "${task_repository}:${task_tag}" \
  --project "$GCP_PROJECT_ID" --format='value(image_summary.digest)')"
if [[ ! "$task_digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo 'Registry did not return an immutable digest' >&2
  exit 1
fi
echo "${task_repository}@${task_digest}"
