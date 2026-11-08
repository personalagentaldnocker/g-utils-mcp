# Design contract

What this project is, what it promises, and the decisions behind it. The README and
`docs/` describe how to use it; this file says what must stay true.

## Scope

- One Cloud Run service exposing Streamable HTTP MCP for Gmail, Drive and Google Docs, used
  first by Claude Code on the web.
- Gmail: search and read messages and threads, manage user labels, label messages and
  threads, read attachments, and create or edit reply drafts with attachments.
- Drive: account-wide list, read, upload, download, update and export. Docs: read, create
  and edit content with revision checks.
- Out of scope for the first release: sending mail, deleting or trashing messages, Drive
  delete or sharing, Sheets/Slides content, Calendar, folder restrictions, an MCP OAuth
  server, and a management UI.

## Invariants

1. **Request order.** Authenticate the bearer token against the current policy generation.
   Check principal → account → tool. Check arguments. Only then read the account's secret
   and call Google. `policy.run()` is the only path to Google.
2. **Deny wins.** Nothing is allowed unless listed. No wildcards or inheritance. Implementing
   a tool never grants it; `allow` may only name implemented tools.
3. **Fresh policy.** On every request the runtime reads the policy object's metadata and
   reloads when the generation changed. If the policy can't be read or is invalid, requests
   are refused. There is no time-based cache, because a revoked grant would keep working
   until the cache expired.
4. **Runtime is read-only for control data.** It can read the policy and account secrets,
   and read/write only the temporary bucket. It cannot write policy, secrets or IAM.
5. **Credentials stay out of Git, Terraform state, logs, tool results and command-line
   arguments.** Tokens are written to new 0600 files or straight to Secret Manager. The
   policy holds only sha256 digests of client tokens.
6. **Administrative code stays out of the image.** `scripts/` is excluded, and
   `google-auth-oauthlib` lives in the `admin` dependency group.
7. **Files never pass through the model.** Bytes go to the temporary bucket behind a
   `file_ref`, which is bound to its principal, expires after 30 minutes, and re-checks
   the source tools' grants on every use. Transfers are logged with size and sha256 only.
8. **Live tests need explicit, disposable test accounts.** Unrun live validation is
   reported as unrun.

## Decisions

| Decision | Reason |
| --- | --- |
| Flat policy (principal → account → tool names) | The check is one function; the old contexts/owners layer added nothing for the owner's use |
| Tool name = method id with `_` | Grants read like the API; tool names stayed the same across the v1→v2 migration |
| Token digests inline in the policy | A sha256 of a 32-byte random token is not a usable credential, so the per-principal secrets and IAM weren't needed |
| Generation check on every request | Revocation is immediate; costs one metadata read |
| Google sign-in on the operator's laptop (`InstalledAppFlow`) | Only the owner or self-deployers connect accounts. Removes the OAuth callback, enrollment intents, `PUBLIC_BASE_URL` and the two-phase deploy |
| One authorized-user secret per account | `google.oauth2.credentials.Credentials` needs refresh token and client in one place; google-auth handles refresh |
| `googleapiclient.discovery.build()` with bundled discovery docs plus one generic dispatcher | Custom code only where needed: drafts, attachments, upload/download |
| Google page tokens passed through | Only usable with the same account's credentials, and every call is re-checked anyway |
| DNS-rebinding host check disabled | Browsers can't attach the bearer token; the check required a known public URL |
| Static bearer token for MCP clients | What Claude Code cloud sessions support today; real-session support is an acceptance gate (docs/claude-cloud.md) |
| Separate Terraform roots (bootstrap, foundation, service) | No cycles; image digest pinned; apply only after a shown plan and an explicit `yes` |

## Layout

```text
src/g_utils_mcp/{app,policy,gmail,drive,utils,cli}.py
scripts/admin.py, build.sh, deploy.sh, smoke.py, verify_image.sh, build-local-offline.sh
infrastructure/{bootstrap,foundation,service}/
examples/policy.{example,deny-all}.yml
tests/
docs/{setup,policy,claude-cloud,operations,terraform,api-coverage}.md
```
