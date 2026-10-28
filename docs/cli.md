# Operator CLI

Run from the checkout root with `uv run python scripts/SCRIPT.py`. --help describes
actual options. Use ignored local/ files for policies and credentials.

| Script | Commands / purpose |
| --- | --- |
| doctor.py | --local checks versions/tools; configured-cloud mode reads current policy, identities and callback configuration. It doesn't prove every Google scope works. |
| gcs_policy.py | validate/pull/diff/publish --file PATH; history; rollback --generation OLD --expected-generation CURRENT [--yes]. |
| auth.py | connect/reconnect --account ALIAS --service gmail\|drive; status --intent ID; activate --intent ID --policy-file PATH. |
| accounts.py | add/status/disable/remove local bindings; explicit revoke-google for Google consent revocation. |
| clients.py | initialize template credential; create another principal; rotate to a new digest ref; revoke principal or old digest ref. |
| secret_cli.py | write --ref REF (hidden prompt); versions --ref REF (metadata only). |
| configure_service.py | --image DIGEST [--public-base-url URL] writes non-secret service inputs from foundation outputs. |
| generate_api_catalog.py | regenerate reviewed pinned-Discovery coverage, or --check. |
| smoke.py | read-only authenticated real MCP initialize/discovery/capabilities check using MCP_URL/MCP_TOKEN. |

Examples:

```bash
uv run python scripts/gcs_policy.py publish --file local/policy.yml
uv run python scripts/gcs_policy.py history
uv run python scripts/gcs_policy.py rollback --generation OLD --expected-generation CURRENT
uv run python scripts/accounts.py status --policy-file local/policy.yml
uv run python scripts/accounts.py disable --policy-file local/policy.yml --account mailbox
# Review diff and publish to make local disable effective.
uv run python scripts/clients.py rotate --policy-file local/policy.yml --principal claude-cloud --digest-ref "projects/$GCP_PROJECT_ID/secrets/NEW_DIGEST/versions/latest" --output local/new-token
# Publish overlap; configure clients; remove old digest ref and republish:
uv run python scripts/clients.py revoke --policy-file local/policy.yml --principal claude-cloud --digest-ref 'OLD_SECRET_VERSION_REF'
```

A rotate target must be a different Terraform-created secret. Keep at most three
refs during overlap. `revoke` without --digest-ref disables the principal. Google
consent revocation is a different explicit command: it may affect other grants
for the same Google user/client. Disable the policy first for immediate server-side
revocation; don't rely on a remote token revocation being instantaneous.

`accounts.py add` options: --policy-file, --account, --owner, --email, --service,
--oauth-client, --token-ref and repeatable --scope. It stages a disabled binding;
add its secret container in Terraform first. Status reports no token values.

Shell scripts: build.sh pushes a revision-tagged linux/amd64 image and reports the
immutable digest; deploy.sh shows/applies the service plan and checks health;
verify_image.sh IMAGE checks runtime packaging. build-local-offline.sh uses the
verified host uv cache when Docker's own package-network access is unavailable.

## File transfer client

Supply MCP_URL as an HTTPS origin and MCP_TOKEN securely in the client environment.

```bash
uv run g-utils upload /tmp/input.pdf --context private
# Supply the returned file_ref to gmail_draft_compose or drive_upload.
uv run g-utils download FILE_REF /tmp/new-download.pdf --context private
```

Downloads never overwrite existing files, validate checksums, and remove partial
outputs after transfer failure. Requests are authenticated and scoped to context;
no public artifact URL or shared filesystem is assumed. Transfer defaults to 20 MB.
