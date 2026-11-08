# g-utils-mcp

An MCP server on Cloud Run that gives an agent (e.g. Claude Code) access to Gmail and
Drive/Docs, limited by a policy file you control. No sending mail, no deleting.

## Use it from Claude Code

`.mcp.json` in the repository root registers the server. Make two variables available
where Claude Code runs:

- `MCP_URL`: the service URL printed by `scripts/deploy.sh` (no trailing slash).
- `MCP_TOKEN`: the content of `local/mcp-token` (see step 6).

In a cloud session, set both in the environment's settings and allow the Cloud Run host
in its network settings. Locally, export both in the shell that starts `claude`. Start a
new session; `/mcp` should show `g-utils-mcp`.

## Set up

Needs: gcloud (logged in, project selected), `gcloud auth application-default login`,
uv, Terraform (version in `.terraform-version`). Run everything from the repository root.

1. **Settings.** `cp .env.example .env`, set `GCP_PROJECT_ID` and `GCP_REGION`, then
   `set -a; source .env; set +a`. Run `uv sync --locked --all-groups`.
2. **Infrastructure.**
   ```bash
   cp infrastructure/foundation/terraform.example.tfvars infrastructure/foundation/terraform.tfvars
   terraform -chdir=infrastructure/foundation init
   terraform -chdir=infrastructure/foundation apply
   ```
   This creates the APIs, the runtime service account, the image registry, the policy
   bucket, the temporary bucket for large files and the single secret (empty).
3. **OAuth client (Cloud Console, manual).** Google Auth Platform → Branding and
   Audience: set the app to **In production** (in Testing, sign-ins expire after 7 days;
   for personal use you click past the "unverified app" warning once). Clients → Create
   → **Desktop app** → download the JSON to `local/client_secret.json`, then:
   ```bash
   uv run python scripts/admin.py client --file local/client_secret.json
   ```
4. **Policy.** `cp examples/policy.example.yml local/policy.yml`, set the
   `expected_email` of each account and remove accounts you don't use, then:
   ```bash
   uv run python scripts/admin.py policy-push --file local/policy.yml
   ```
5. **Sign in each account.** A browser opens; sign in as the account's `expected_email`.
   A different account is refused.
   ```bash
   uv run python scripts/admin.py login --account mailbox
   ```
   Then set `enabled: true` for that account in `local/policy.yml` and push again.
6. **Agent token.** Written to a private file, never printed:
   ```bash
   uv run python scripts/admin.py token --principal claude-cloud --output local/mcp-token
   ```
7. **Build and deploy.** `deploy.sh` shows the Terraform plan and asks before applying.
   ```bash
   bash scripts/build.sh
   ```
   ```bash
   cp infrastructure/service/terraform.example.tfvars infrastructure/service/terraform.tfvars
   ```
   Fill it in from `terraform -chdir=infrastructure/foundation output`, then:
   ```bash
   bash scripts/deploy.sh
   ```
8. **Check.** With `MCP_URL` and `MCP_TOKEN` set: `uv run python scripts/smoke.py`.

## Change permissions

```bash
uv run python scripts/admin.py policy-pull --file local/policy.yml
```
Edit, then `policy-push`. The push fails if someone changed the policy since your pull.
The server checks the policy on every request, so changes apply immediately.

## Policy format

`principals` are agents (one token each), `accounts` are Google accounts with the
services they're signed in for, and `contexts.<name>.grants.<principal>.<account>` lists
the allowed and denied Google methods. Deny wins; anything not allowed is denied. See
`examples/policy.example.yml`. Tool names are method names with `_`, e.g.
`gmail.users.messages.list` → `gmail_users_messages_list`.

Every tool call passes `context`, `account` and `params` (the Google method's
parameters). Start with `workspace_capabilities`.

## Files

Up to 5 MB, files (attachments, Drive uploads and downloads) travel inline as
`data_base64`. Up to 25 MB, they go through the temporary bucket:

- **Download:** the tool returns a `file_ref` instead of data.
  ```bash
  curl -fsS -H "Authorization: Bearer $MCP_TOKEN" -o out.pdf "$MCP_URL/files/FILE_REF"
  ```
- **Upload:** post the file, then pass the returned `file_ref` to `drive_upload` or in
  `add_files` of `gmail_draft_compose`.
  ```bash
  curl -fsS -H "Authorization: Bearer $MCP_TOKEN" -H "X-Filename: report.pdf" -H "Content-Type: application/pdf" --data-binary @report.pdf "$MCP_URL/files"
  ```

A `file_ref` works only with the token that created it and for one hour; the bucket
deletes everything after a day. The bucket holds file contents only, never tokens.

## Tear down

```bash
terraform -chdir=infrastructure/service destroy
terraform -chdir=infrastructure/foundation destroy
```
This deletes the service, the secret and both buckets. Enabled APIs stay on.

## Development

```bash
uv run ruff check . && uv run mypy src && uv run pytest
```

Layout: `src/g_utils_mcp/app.py` (HTTP + `/mcp`), `mcp_server.py` (tools),
`services/gmail.py`, `services/drive.py`, `utils/auth.py` (token, policy, Google
credentials), `utils/helpers.py` (Cloud Storage, Secret Manager, Google API calls).
Operator commands are in `scripts/admin.py` and are not part of the image.
