#!/usr/bin/env bash
# Plan the Cloud Run service, show the plan, and apply it only after explicit confirmation.
# Reads the operator's own infrastructure/service/terraform.tfvars; never writes it.
set -euo pipefail
cd "$(dirname "$0")/.."
root=infrastructure/service
if [[ ! -f "$root/terraform.tfvars" && ! -f "$root/terraform.tfvars.json" ]]; then
  echo "Create $root/terraform.tfvars from terraform.example.tfvars first." >&2
  exit 1
fi
terraform -chdir="$root" init -input=false
terraform -chdir="$root" plan -input=false -out=tfplan
terraform -chdir="$root" show tfplan
read -r -p "Apply this plan? Type 'yes' to continue: " answer
if [[ "$answer" != "yes" ]]; then
  echo "Not applied." >&2
  exit 1
fi
terraform -chdir="$root" apply tfplan
url="$(terraform -chdir="$root" output -raw service_url)"
curl --fail --silent --show-error "${url}/healthz"
echo
