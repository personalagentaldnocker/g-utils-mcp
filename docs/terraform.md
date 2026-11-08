# Terraform details

Terraform 1.13.5 and provider google 7.8.0 are pinned; lockfiles are committed. Three roots:

- `bootstrap/`: optional private, versioned state bucket.
- `foundation/`: APIs, runtime service account, image repository, policy bucket (versioned),
  temporary bucket (1-day lifecycle) and secret shells.
  - The runtime gets read-only access to the policy bucket, object access to the temporary
    bucket, and `secretAccessor` on the account token secrets only.
  - It cannot write policy, secrets or IAM.
- `service/`: Cloud Run pinned to an image digest, plus public invocation. Application
  authentication is still required on every route except `/healthz`.

Public invocation is needed because Claude cannot mint Google IAM ID tokens. If your
organization forbids `allUsers` invokers, resolve that before deploying.

tfvars files belong to the operator and are Git-ignored. Scripts read them and never
write them. Always `plan -out`, read the plan, then `apply` that plan;
`scripts/deploy.sh` asks for confirmation before applying.

## Names

Defaults derive from `name = "g-utils-mcp"`:
- Cloud Run service, service account and repository: `g-utils-mcp`;
- buckets: `PROJECT-g-utils-mcp-policy` and `PROJECT-g-utils-mcp-temporary`;
- policy object: `policies/g-utils-mcp-v2.yml`.

Keep `name` the same in foundation and service.

## Remote state (optional)

```bash
terraform -chdir=infrastructure/bootstrap init
terraform -chdir=infrastructure/bootstrap apply -var="project_id=$GCP_PROJECT_ID"
export TF_STATE_BUCKET="$(terraform -chdir=infrastructure/bootstrap output -raw state_bucket)"
```

Add an ignored `backend.tf` with `terraform { backend "gcs" {} }` to foundation and service,
then:

```bash
terraform -chdir=infrastructure/foundation init -migrate-state -backend-config="bucket=$TF_STATE_BUCKET" -backend-config='prefix=foundation'
terraform -chdir=infrastructure/service init -migrate-state -backend-config="bucket=$TF_STATE_BUCKET" -backend-config='prefix=service'
```

State holds no secret values, but keep it private anyway.

## Imports

For an existing project, import what already exists instead of recreating it. For example:

```bash
terraform -chdir=infrastructure/foundation import 'google_project_service.required["gmail.googleapis.com"]' "$GCP_PROJECT_ID/gmail.googleapis.com"
terraform -chdir=infrastructure/foundation import google_service_account.runtime "projects/$GCP_PROJECT_ID/serviceAccounts/g-utils-mcp@$GCP_PROJECT_ID.iam.gserviceaccount.com"
terraform -chdir=infrastructure/foundation import google_storage_bucket.policy 'ACTUAL_POLICY_BUCKET'
terraform -chdir=infrastructure/foundation import 'google_secret_manager_secret.managed["gmail-main-refresh"]' "projects/$GCP_PROJECT_ID/secrets/gmail-main-refresh"
terraform -chdir=infrastructure/service import google_cloud_run_v2_service.runtime "projects/$GCP_PROJECT_ID/locations/$GCP_REGION/services/g-utils-mcp"
```

Buckets and secrets have `prevent_destroy`, and Cloud Run has deletion protection. Teardown
requires deliberately changing those.

## Retiring v1 secrets

`oauth_client_secrets` and `principal_digest_secrets` exist only so a v1 installation's
secrets are not destroyed (which `prevent_destroy` would block anyway). After migrating,
for each name:

```bash
terraform -chdir=infrastructure/foundation state rm 'google_secret_manager_secret.managed["NAME"]'
gcloud secrets delete NAME --project "$GCP_PROJECT_ID"
```

Then set both variables to `[]` and plan again; the plan should show no changes.

## Image

```bash
bash scripts/build.sh                      # pushes and prints repository@sha256:…
docker build -t g-utils-mcp:local . && bash scripts/verify_image.sh g-utils-mcp:local
```

If Docker cannot reach package registries but host uv can, use
`bash scripts/build-local-offline.sh`. The image contains only `src/` and runtime
dependencies, and runs as UID 10001.
