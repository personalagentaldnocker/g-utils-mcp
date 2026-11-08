# Policy file

One YAML object in the policy bucket decides who may do what. The runtime can only read it.

```yaml
version: 2
revision: 2026-11-08-a            # free text, for your own tracking
principals:
  claude-cloud:
    token_sha256: [9f86d0…]       # sha256 hex of each valid bearer token, up to 3
accounts:
  mailbox:
    email: mailbox@example.net
    secret: projects/P/secrets/gmail-main-refresh/versions/latest
grants:
  claude-cloud:
    mailbox:
      allow: [gmail_users_messages_list, gmail_users_messages_get]
      deny:  [gmail_users_messages_send]
```

- **principals**: a client token looks like `claude-cloud.<random>`. The server hashes it and
  compares the result with that principal's `token_sha256`. A digest can't be turned back
  into a token, so the policy holds no usable credential. `admin.py token new` creates a
  token and adds its digest.
- **accounts**: a Google account alias, its expected email, and the Secret Manager version
  that holds its authorized-user JSON (written by `admin.py connect`).
- **grants**: principal → account → tool names. A call is allowed only if the tool is in
  `allow` and not in `deny`. Deny wins. There are no wildcards, defaults or inheritance.

## Rules the parser enforces

- Unknown keys, duplicate keys, YAML aliases/anchors/tags and files over 1 MB are rejected.
- Grants must reference existing principals and accounts.
- `allow` may only name implemented tools ([api-coverage.md](api-coverage.md)).
  Implementing a tool never grants it. `deny` may name anything, including tools that
  don't exist, as a guard against future additions.
- Secret refs must match `projects/*/secrets/*/versions/*`. At runtime they must also be in
  `ALLOWED_SECRET_PROJECTS` and readable by the runtime's IAM.

## How changes take effect

The server loads the policy at startup and, on every request, reads only the object's
metadata. When the generation changed, it downloads and validates that exact generation.
A revocation therefore applies to the next request. If the new generation is invalid or
unreadable, every request is refused until a valid one is published; there is no fallback
to the last good policy.

```bash
uv run python scripts/admin.py policy pull local/policy.yml          # current version
uv run python scripts/admin.py policy validate local/policy.yml
uv run python scripts/admin.py policy publish local/policy.yml       # diff, confirm, publish
uv run python scripts/admin.py policy history
uv run python scripts/admin.py policy pull local/old.yml --generation N   # then publish to roll back
```

`publish` writes with `ifGenerationMatch`, so it fails instead of overwriting a newer
policy.

## Helper tools and their grants

Helpers need their own name **and** the grants of the Google methods they use:

| Helper | Also needs |
| --- | --- |
| `gmail_attachment_download` | `gmail_users_messages_get`, plus `gmail_users_messages_attachments_get` for non-inline parts |
| `gmail_draft_compose` | `gmail_users_drafts_create` or `_update`; `_drafts_get` to edit; `_messages_get` to reply |
| `drive_upload` | `drive_files_create` or `drive_files_update` |
| `drive_download` | `drive_files_get`; `drive_files_export` for Google Docs/Sheets/Slides |

`drive_files_export` is a grant name only, not a tool of its own.

## Fixed argument rules (all grants)

- Gmail: `userId` is always `me`. Adding `TRASH`/`SPAM` labels is blocked. Only user labels
  (`Label_*`) can be edited or deleted.
- Drafts: `gmail_users_drafts_update` and `gmail_draft_compose` require the unchanged
  `revision` returned by `gmail_users_drafts_get`.
- Drive create/update may set only `name`, `description`, `mimeType` (and `parents` on
  create). Moving, trashing and sharing are not possible.
- Docs: `documents.create` takes only a title. `batchUpdate` needs
  `writeControl.requiredRevisionId`, at most 100 requests, and only text, style and table
  requests.
- Every call's `params` are validated against Google's discovery schema. Unknown fields
  are rejected and page sizes are limited to 1–100.

## Files

`gmail_attachment_download`, `gmail_users_messages_attachments_get` and `drive_download`
return a `file_ref` instead of bytes. The bytes go to the temporary bucket for 30 minutes.
A `file_ref` works only for the principal that created it. Each time it is used, the tools
that produced it must still be granted, so revoking a grant also blocks its files.
