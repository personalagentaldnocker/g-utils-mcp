# Terraform, builds and deployment

Commands run from the checkout root. Provider Google 7.8.0 and Terraform 1.13.5
are pinned; commit provider lockfiles. Separate roots avoid bootstrap cycles:

- bootstrap/: optional private versioned Terraform state bucket.
- foundation/: APIs, runtime SA, image repository, policy/temp buckets, secret shells
  and additive IAM. Only designated refresh secrets permit runtime version additions.
- service/: digest-pinned Cloud Run and public invocation. MCP/files still require
  application authentication. OAuth uses administrative single-use intents.

The public invocation setting allows clients that cannot mint GCP IAM ID tokens.
If organization policy forbids it, resolve the ingress design before deploying.
No ordinary MCP credential can administer the project.

## State

Local state is the initial default. Keep it private. For optional remote state:

```bash
terraform -chdir=infrastructure/bootstrap init
terraform -chdir=infrastructure/bootstrap apply -var="project_id=$GCP_PROJECT_ID"
export TF_STATE_BUCKET="$(terraform -chdir=infrastructure/bootstrap output -raw state_bucket)"
```

Create ignored backend.tf in each foundation/service root with:

```hcl
terraform {
  backend "gcs" {}
}
```

```bash
terraform -chdir=infrastructure/foundation init -migrate-state -backend-config="bucket=$TF_STATE_BUCKET" -backend-config='prefix=foundation'
terraform -chdir=infrastructure/service init -migrate-state -backend-config="bucket=$TF_STATE_BUCKET" -backend-config='prefix=service'
```

GCS backend locking prevents concurrent writes. Restrict operator access: even
without token values, state contains infrastructure metadata. Preserve bootstrap
state locally or migrate it to a third prefix after creation. Don't use temp/policy
buckets for Terraform state.

## Build/deploy

After foundation and deny-all policy are prepared:

```bash
bash scripts/build.sh
# Set this to the final repository@sha256:... line from build.sh:
export IMAGE_DIGEST='YOUR_REGISTRY_IMAGE@sha256:64_HEX_CHARACTERS'
uv run python scripts/configure_service.py --image "$IMAGE_DIGEST"
bash scripts/deploy.sh
export PUBLIC_BASE_URL="$(terraform -chdir=infrastructure/service output -raw service_url)"
uv run python scripts/configure_service.py --image "$IMAGE_DIGEST" --public-base-url "$PUBLIC_BASE_URL"
bash scripts/deploy.sh
```

configure_service.py reads foundation outputs and writes ignored non-secret service
terraform.tfvars.json. Use it OR your own service tfvars, not conflicting files.
Review both plans; the second apply sets the real URL. Then register its Google
callback and follow authentication.md. No terraform -target is needed.

```bash
docker build -t google-utils-mcp:local .
bash scripts/verify_image.sh google-utils-mcp:local
```

If the Docker builder cannot reach registries but host uv can install, use
`bash scripts/build-local-offline.sh`. It builds from uv's verified cache without
disabling integrity/TLS checks. Only runtime dependencies reach the final image.

## Imports

Inspect existing identities/locations first and adapt inputs to preserve them.
Examples, with actual names substituted:

```bash
terraform -chdir=infrastructure/foundation import 'google_project_service.required["gmail.googleapis.com"]' "$GCP_PROJECT_ID/gmail.googleapis.com"
terraform -chdir=infrastructure/foundation import google_service_account.runtime "projects/$GCP_PROJECT_ID/serviceAccounts/google-utils-mcp@$GCP_PROJECT_ID.iam.gserviceaccount.com"
terraform -chdir=infrastructure/foundation import google_storage_bucket.policy 'ACTUAL_POLICY_BUCKET'
terraform -chdir=infrastructure/foundation import 'google_secret_manager_secret.managed["oauth-workspace-client-secret"]' "projects/$GCP_PROJECT_ID/secrets/oauth-workspace-client-secret"
terraform -chdir=infrastructure/service import google_cloud_run_v2_service.runtime "projects/$GCP_PROJECT_ID/locations/$GCP_REGION/services/google-utils-mcp"
```

Scripts never create secret shells behind Terraform. Add token/digest names to
foundation sets and apply before writing values. Buckets are private; policy is
versioned. Temporary data has a one-day lifecycle and no soft-delete retention;
application expiry is enforced sooner. Policy/secrets prevent_destroy and Run
deletion protection must be deliberately changed for teardown.

Rollback: retain prior digests and inputs, set the chosen previous digest, inspect
and apply the service plan, then rerun smoke checks. Roll back policy separately
with its generation-guarded CLI.
