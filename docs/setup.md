# Setup

From an empty or existing GCP project to a working MCP endpoint. Run everything from the
checkout root as the **operator** (your own Google identity, via ADC). Nothing here puts a
credential in Git, Terraform state, logs or a command-line argument.

## 1. Tools and login

Install [uv](https://docs.astral.sh/uv/), the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install),
Terraform **1.13.5** and Docker with buildx.

```bash
export GCP_PROJECT_ID='your-project-id'
export GCP_REGION='europe-west3'
gcloud auth login
gcloud config set project "$GCP_PROJECT_ID"
gcloud auth application-default login
gcloud auth application-default set-quota-project "$GCP_PROJECT_ID"
uv sync --locked --all-groups
```

Python and Terraform use ADC. An unrelated `GOOGLE_APPLICATION_CREDENTIALS` overrides it.

A fresh project needs billing and two bootstrap APIs:

```bash
gcloud projects create "$GCP_PROJECT_ID"
gcloud billing projects link "$GCP_PROJECT_ID" --billing-account='YOUR_BILLING_ACCOUNT_ID'
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com
```

For an existing project, see [terraform.md](terraform.md#imports) before applying.

## 2. Foundation (APIs, buckets, runtime identity, secret shells)

Create your own tfvars once. No script writes or overwrites it.

```bash
cp infrastructure/foundation/terraform.example.tfvars infrastructure/foundation/terraform.tfvars
```

List one secret name per Google account in `refresh_token_secrets`. Then:

```bash
terraform -chdir=infrastructure/foundation init
terraform -chdir=infrastructure/foundation plan -out=tfplan
terraform -chdir=infrastructure/foundation apply tfplan
export POLICY_URI="$(terraform -chdir=infrastructure/foundation output -raw policy_uri)"
```

`apply tfplan` applies exactly the plan you just reviewed.

## 3. Policy

```bash
mkdir -p local
cp examples/policy.example.yml local/policy.yml
```

Edit `local/policy.yml`: keep the accounts you want, set their real `email` and the
`secret` refs printed by `terraform -chdir=infrastructure/foundation output secret_refs`,
and trim the grants. Then create the client token (written to a new 0600 file, never
printed) and publish:

```bash
uv run python scripts/admin.py token new claude-cloud --policy-file local/policy.yml --output local/mcp-token
uv run python scripts/admin.py policy publish local/policy.yml
```

`publish` shows a diff and asks before writing. It fails if someone else published in the
meantime. Details: [policy.md](policy.md).

## 4. Google OAuth client

In Cloud Console → **Google Auth Platform**, set Branding, Audience and Data Access, then
under **Clients** create a **Desktop app** client and download its JSON to
`local/oauth-client.json` (Git-ignored). Desktop clients use a loopback redirect, so no
server URL is involved. External apps in "Testing" state get refresh tokens that expire
after seven days.

## 5. Connect each Google account

```bash
uv run python scripts/admin.py connect mailbox --policy-file local/policy.yml --client-secrets local/oauth-client.json --scope https://www.googleapis.com/auth/gmail.modify
uv run python scripts/admin.py connect drive-agent --policy-file local/policy.yml --client-secrets local/oauth-client.json --scope https://www.googleapis.com/auth/drive
```

A browser opens on your laptop. After consent, the command checks that you signed in as the
account's `email` and adds the refresh token as a new version of the account's secret. The
token is held only in memory. `drive` scope also covers the Docs methods.

## 6. Build and deploy

```bash
bash scripts/build.sh
cp infrastructure/service/terraform.example.tfvars infrastructure/service/terraform.tfvars
```

Fill in `terraform.tfvars` from the foundation outputs and the `repository@sha256:…` line
that `build.sh` printed, then:

```bash
bash scripts/deploy.sh
```

`deploy.sh` shows the plan and applies only after you type `yes`. One deploy is enough: the
server does not need to know its own URL.

The new revision only starts if the policy at `POLICY_URI` is readable and valid. Otherwise
Cloud Run keeps serving the previous revision.

## 7. Check it

```bash
export MCP_URL="$(terraform -chdir=infrastructure/service output -raw service_url)"
export MCP_TOKEN="$(cat local/mcp-token)"
uv run python scripts/smoke.py
```

Then configure Claude Code: [claude-cloud.md](claude-cloud.md).
