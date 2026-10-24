# Initial authentication

Three identities remain separate: operator GCP ADC, agent MCP credential, and Google
account OAuth grant. Cloud Run uses its assigned SA to access approved secret refs.

## Prepare policy and secret

```bash
mkdir -p local
uv run python scripts/gcs_policy.py pull --file local/policy.yml
```

Use examples/policy.example.yml as the feature template. Replace local/policy.yml's
contents with your adapted template, retaining its .generation sidecar. Replace
project/client IDs and expected emails; keep accounts disabled and subjects empty.
The template principal can exist before its empty digest secret is initialized.
All identifiers in examples are artificial. Real mappings stay outside Git.

```bash
uv run python scripts/secret_cli.py write --ref "projects/$GCP_PROJECT_ID/secrets/oauth-workspace-client-secret/versions/latest"
uv run python scripts/gcs_policy.py validate --file local/policy.yml
uv run python scripts/gcs_policy.py diff --file local/policy.yml
uv run python scripts/gcs_policy.py publish --file local/policy.yml
```

Secret input is hidden. secret_cli.py avoids shadowing Python's stdlib secrets
module. Shells must already exist from Terraform. Don't put values in tfvars/args.

## Connect and activate

```bash
uv run python scripts/auth.py connect --account mailbox --service gmail
uv run python scripts/auth.py status --intent ENROLLMENT_ID
uv run python scripts/auth.py activate --intent ENROLLMENT_ID --policy-file local/policy.yml
uv run python scripts/gcs_policy.py diff --file local/policy.yml
uv run python scripts/gcs_policy.py publish --file local/policy.yml

uv run python scripts/auth.py connect --account drive-agent --service drive
uv run python scripts/auth.py status --intent ITS_NEW_ENROLLMENT_ID
uv run python scripts/auth.py activate --intent ITS_NEW_ENROLLMENT_ID --policy-file local/policy.yml
uv run python scripts/gcs_policy.py diff --file local/policy.yml
uv run python scripts/gcs_policy.py publish --file local/policy.yml
```

Use the command's own printed enrollment ID. --no-open-browser prints the explicit
short-lived link for another browser. Intents expire in ten minutes and are usable
for one enrollment. State, PKCE, nonce, verified email, stable Google subject and
scopes are checked; transaction data persists across instances. Callback writes a
refresh-secret version but never policy. Activation changes your local file only;
publication is explicit. Docs reuses the dedicated Drive account's credential.

For failure/revoked grants, start `auth.py reconnect --account ... --service ...`.
A consumed callback/code cannot be reused. Normal access-token expiry is refreshed
automatically; only short-lived access tokens are cached, isolated by account/binding.

## Initial MCP credential

For the principal already defined by the template:

```bash
uv run python scripts/clients.py initialize --policy-file local/policy.yml --principal claude-cloud --output local/mcp-token
```

This requires its digest secret to have no existing version. It writes the digest
to Secret Manager and the random credential to an exclusive mode-0600 file, never
stdout. Load the credential into Claude's secure environment; no chat/Git values.

For another principal, use clients.py create with --policy-file, --principal,
--owner, --context, --digest-ref and --output, then add explicit grants and publish.
Create a separate Terraform digest container first. A read-only agent can share
an account while having only list/get/export methods. An agent cannot select a
foreign account or create enrollment intents. Cross-owner grants are rejected.

Rotation uses a different pre-created digest secret, a short policy overlap,
client credential replacement, then removal of the old reference. See cli.md.
