#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
terraform -chdir=infrastructure/service init
terraform -chdir=infrastructure/service plan -out=tfplan
terraform -chdir=infrastructure/service show tfplan
terraform -chdir=infrastructure/service apply tfplan
task_service_url="$(terraform -chdir=infrastructure/service output -raw service_url)"
curl --fail --silent --show-error "${task_service_url}/healthz"
