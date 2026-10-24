# GCP setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/),
[Google Cloud CLI](https://cloud.google.com/sdk/docs/install), Terraform **1.13.5**,
and Docker/buildx from their official distributions. Use Python 3.12 (uv manages it).
Run commands from the checkout root under your **operator identity**.

```bash
export GCP_PROJECT_ID='your-project-id'
export GCP_REGION='europe-west3'
gcloud auth login
gcloud config set project "$GCP_PROJECT_ID"
gcloud auth application-default login
gcloud auth application-default set-quota-project "$GCP_PROJECT_ID"
uv sync --locked --all-groups
uv run python scripts/doctor.py --local
```

`gcloud auth login` and ADC serve different consumers: Python/Terraform use ADC.
An unrelated GOOGLE_APPLICATION_CREDENTIALS file overrides the local ADC login.
Cloud Run uses its assigned service account, with no downloaded service-account key.

## Existing project

Inspect first; reuse your already-enabled APIs and production OAuth app:

```bash
gcloud projects describe "$GCP_PROJECT_ID"
gcloud billing projects describe "$GCP_PROJECT_ID"
gcloud services list --enabled --project "$GCP_PROJECT_ID"
```

Import existing infrastructure as described in terraform.md. Production OAuth
publishing status is separate from restricted-scope verification and any applicable
assessment. Check requirements for the audience/accounts you intend to connect.

## Fresh project

Choose a globally unique ID and link your billing account. Organization policies
may require --folder or --organization when creating the project.

```bash
gcloud projects create "$GCP_PROJECT_ID" --name='Google Utils MCP'
gcloud billing accounts list
gcloud billing projects link "$GCP_PROJECT_ID" --billing-account='YOUR_BILLING_ACCOUNT_ID'
gcloud config set project "$GCP_PROJECT_ID"
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com --project "$GCP_PROJECT_ID"
gcloud auth application-default set-quota-project "$GCP_PROJECT_ID"
```

The operator needs permission to enable services, manage these resources and their
IAM, push images, deploy Run, and act as the runtime SA. Follow your organization's
operator role policy. The runtime SA never receives Owner/Editor or administrative
credentials. A separate deployer needs Artifact Registry writer on the repository,
Run deployment permissions, and Service Account User on this runtime SA.

## Foundation

```bash
cp infrastructure/foundation/terraform.example.tfvars infrastructure/foundation/terraform.tfvars
# Edit project_id/region and secret-container names. No secret values.
terraform -chdir=infrastructure/foundation init
terraform -chdir=infrastructure/foundation plan -out=tfplan
terraform -chdir=infrastructure/foundation show tfplan
terraform -chdir=infrastructure/foundation apply tfplan
export GOOGLE_CLOUD_PROJECT="$GCP_PROJECT_ID"
export POLICY_URI="$(terraform -chdir=infrastructure/foundation output -raw policy_uri)"
export TEMP_BUCKET="$(terraform -chdir=infrastructure/foundation output -raw temporary_bucket)"
export ALLOWED_SECRET_PROJECTS="[\"${GCP_PROJECT_ID}\"]"
uv run python scripts/gcs_policy.py validate --file examples/policy.deny-all.yml
uv run python scripts/gcs_policy.py publish --file examples/policy.deny-all.yml --create
```

--create is generation-zero only. For an existing policy, pull and publish against
its recorded generation. Terraform enables Run, Registry, Secret Manager, Storage,
IAM, Gmail, Drive and Docs APIs without disabling retained APIs on destroy. The
local Docker build path needs no Cloud Build API or build identity.

Follow terraform.md to build/deploy and obtain PUBLIC_BASE_URL. First deployment
can leave it empty: health starts but enrollment/remote MCP aren't ready until the
actual URL is configured in the second reviewed deployment.

## Google OAuth web client

In Cloud Console → **Google Auth Platform**, check **Branding**, **Audience** and
**Data Access**. Use an appropriate internal/external audience and production state.
Under **Clients**, select/create a **Web application** client and register the exact
**Authorized redirect URI**: `https://YOUR_RUN_HOST/oauth/google/callback`.
No wildcard/trailing slash. Store its non-secret client ID in the local policy.
Enter the client secret through the hidden-input CLI in authentication.md.

Requested scopes: Gmail gmail.modify; dedicated Drive account drive (also sufficient
for these Docs methods); plus openid and verified email for identity. A broader
Google token still obeys the finer GCS policy. External testing apps may have
short-lived refresh grants. Additional scopes require renewed consent.

General web OAuth client/consent configuration is documented as a console step;
this project does not invent unsupported Terraform resources or gcloud commands.
Other people's accounts must complete their own consent; expected email and stable
Google subject are verified before activation.

References: https://cloud.google.com/docs/authentication/provide-credentials-adc
and https://developers.google.com/identity/protocols/oauth2/web-server.
