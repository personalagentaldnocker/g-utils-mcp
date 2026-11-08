# Operations

## Configuration

Environment variables only; no `.env` file is loaded.

| Name | Purpose |
| --- | --- |
| `POLICY_URI` | `gs://bucket/object` of the policy. Never a tool argument |
| `TEMP_BUCKET` | Temporary file bytes (`files/…`), 30-minute app expiry, 1-day lifecycle |
| `ALLOWED_SECRET_PROJECTS` | JSON array of projects whose secrets may be read, e.g. `["p"]` |
| `PORT` | Listen port, default 8080 |
| `MAX_TRANSFER_BYTES` | File size limit, default 20,000,000 |

## Routes

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /healthz` | none | Liveness |
| `GET /readyz` | bearer | Policy is readable and valid |
| `/mcp` | bearer | Streamable HTTP MCP (stateless, JSON responses) |
| `POST /files` | bearer | Upload bytes, returns a `file_ref` (`g-utils-mcp upload`) |
| `GET /files/{ref}` | bearer | Download a `file_ref` you created (`g-utils-mcp download`) |

Every authenticated request re-checks the bearer token against the current policy
generation.

## Logs

One JSON line per event, with allowlisted fields only. Arguments, bodies, filenames and
tokens are never logged.

- `tool_call`: principal, account, tool, policy generation, error code, duration.
- `file_put` / `file_get`: principal, account, tool, `file_ref`, size in bytes, sha256.
- `policy_loaded`: generation.

Uvicorn access logs are off.

## Limits and behaviour

- Tool results are capped at 1 MB; use `fields` or smaller pages.
- Composed drafts are capped at 30 MB of raw MIME.
- Writes are never retried. `uncertain_write` means the outcome is unknown: check Gmail or
  Drive before trying again.
- Gmail has no atomic draft compare-and-set. The server re-reads the draft just before
  writing, but a manual edit at the same moment can still race.
- A policy change affects the next request, not a Google call already running.
- The runtime can read every account secret granted to its service account. Policy is
  application-level isolation, not protection against compromised server code. Treat
  deploy rights as privileged.

## Common tasks

- **Revoke a client**: remove its digest (or the whole principal) and `policy publish`.
- **Rotate a token**: `admin.py token new` (adds a second digest), publish, switch the
  client, then delete the old digest and publish again.
- **Revoke a grant**: edit `allow`/`deny`, then publish.
- **Google grant expired or revoked** (`reauth_required`): run `admin.py connect` for that
  account again.
- **Roll back the image**: set the previous digest in the service tfvars and run
  `scripts/deploy.sh`.
- **Roll back the policy**: `policy pull --generation N` to a new file, then
  `policy publish` it.

## Migrating a policy v1 deployment

v1 had contexts, owners, digest secrets, separate OAuth client secrets and a server-side
OAuth callback. v2 keeps the same tool names. Steps, in order:

1. `admin.py policy pull local/policy-v1.yml`, with `POLICY_URI` set to the **old** object
   (`…/policies/g-utils-mcp.yml`).
2. `admin.py migrate local/policy-v1.yml local/policy.yml --rewrite-secrets`
   - The migrated policy inlines token digests (read from the digest secrets).
   - It merges contexts and lists helper tools explicitly wherever v1 exposed them.
   - Disabled principals and accounts are left out. Notes are printed for anything that
     changed meaning.
   - `--rewrite-secrets` adds an authorized-user version to each account secret. It keeps
     the v1 fields, so the running v1 service keeps working. An account with separate Gmail
     and Drive secrets must first be split into two accounts.
3. Review `local/policy.yml`. Then, with `POLICY_URI` set to the new `…-v2.yml` object
   (foundation output), run `admin.py policy publish local/policy.yml`.
4. Build the new image, set `policy_uri` to the v2 object and the new digest in your service
   tfvars, delete `public_base_url` from them, and run `scripts/deploy.sh`. The switch
   happens in this one apply.
5. Apply the foundation. This removes the runtime's access to the digest and OAuth-client
   secrets and its secret-write role. The v1 secrets themselves are kept. To retire them,
   see [terraform.md](terraform.md#retiring-v1-secrets).
6. Run `scripts/smoke.py`. New sign-ins use a Desktop OAuth client (setup.md step 4). The
   web client's redirect URI is no longer used.

## Validation status

The non-live pytest suite covers policy parsing, the generation cache, authentication,
deny-wins checks for every tool before credentials load, argument rules, MIME draft
editing, file references, HTTP MCP transport, migration and the CLI.

Not established by these tests, and unrun unless recorded otherwise:
- a real GCP apply;
- Google sign-in and API calls against real accounts;
- deployed IAM;
- the Claude cloud-session checklist ([claude-cloud.md](claude-cloud.md)).

Run the live smoke only with explicitly configured disposable test accounts:
`RUN_LIVE_TESTS=1 uv run pytest -m live`.
