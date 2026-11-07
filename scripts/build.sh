#!/usr/bin/env bash
# Build the image, push it to Artifact Registry and save its digest to local/image-digest.
# BUILDER=cloudbuild (default) builds in Cloud Build; BUILDER=docker builds locally.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
region="${GCP_REGION:-europe-west3}"
repository="$(terraform -chdir=infrastructure/foundation output -raw image_repository)"
tag="$(git rev-parse --short=12 HEAD)"
case "${BUILDER:-cloudbuild}" in
  cloudbuild)
    gcloud builds submit --project "$GCP_PROJECT_ID" --region "$region" --tag "${repository}:${tag}" .
    ;;
  docker)
    gcloud auth configure-docker "${region}-docker.pkg.dev" --quiet
    docker buildx build --platform linux/amd64 --push --provenance=false --tag "${repository}:${tag}" .
    ;;
  *)
    echo "BUILDER must be cloudbuild or docker" >&2
    exit 1
    ;;
esac
digest="$(gcloud artifacts docker images describe "${repository}:${tag}" \
  --project "$GCP_PROJECT_ID" --format='value(image_summary.digest)')"
if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo 'Registry did not return an image digest' >&2
  exit 1
fi
mkdir -p local
echo "${repository}@${digest}" > local/image-digest
echo "Saved ${repository}@${digest} to local/image-digest"
