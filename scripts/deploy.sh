#!/usr/bin/env bash
# Plan the Cloud Run service with the image from local/image-digest, ask, then apply.
set -euo pipefail
cd "$(dirname "$0")/.."
image="$(cat local/image-digest)"
tf=(terraform -chdir=infrastructure/service)
"${tf[@]}" init -input=false
"${tf[@]}" plan -input=false -var "image=${image}" -out=tfplan
read -r -p "Apply this plan? [y/N] " answer
if [[ "$answer" != "y" ]]; then
  echo "Not applied."
  exit 1
fi
"${tf[@]}" apply tfplan
url="$("${tf[@]}" output -raw service_url)"
curl --fail --silent --show-error "${url}/healthz" && echo
echo "MCP_URL=${url}"
