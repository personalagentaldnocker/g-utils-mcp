# Tools

These are all the names a policy can grant (`app.KNOWN`). Adding a name to the code never
grants it to anyone. `tests/test_tools.py` checks that every tool is denied before any
credentials load when it isn't granted.

## Gmail (`gmail.v1`)

| Tool | Notes |
| --- | --- |
| `gmail_users_getProfile` | |
| `gmail_users_messages_list`, `_get` | Gmail `q` search; page tokens are Google's own |
| `gmail_users_messages_modify`, `gmail_users_threads_modify` | Labels only; adding `TRASH`/`SPAM` is blocked |
| `gmail_users_messages_attachments_get` | Returns a `file_ref`, not bytes (`filename` argument optional) |
| `gmail_users_threads_list`, `_get` | |
| `gmail_users_labels_list`, `_get`, `_create`, `_update`, `_patch`, `_delete` | Edit/delete only `Label_*` user labels |
| `gmail_users_drafts_list`, `_create` | |
| `gmail_users_drafts_get` | Returns headers, attachment refs and a `revision`, not raw MIME |
| `gmail_users_drafts_update` | Needs top-level `expected_revision` |
| `gmail_attachment_download` | Helper: any MIME part by `message_id` + `part_id` → `file_ref` |
| `gmail_draft_compose` | Helper: new/reply/edit draft, add `file_ref`s, remove attachment refs; never sends |

## Drive (`drive.v3`) and Docs (`docs.v1`)

| Tool | Notes |
| --- | --- |
| `drive_files_list`, `drive_files_get` | Account-wide, including files shared with the account |
| `drive_files_create`, `drive_files_update` | Metadata only: name, description, mimeType (parents on create) |
| `drive_upload` | Helper: `file_ref` → new file or new content of `file_id` |
| `drive_download` | Helper: file or export (PDF by default) → `file_ref`; follows shortcuts |
| `drive_files_export` | Grant only, required by `drive_download` for Google-native files |
| `docs_documents_get`, `docs_documents_create` | Create takes a title only |
| `docs_documents_batchUpdate` | Needs `writeControl.requiredRevisionId`; text, style and table requests only |

## Always available

`workspace_capabilities` lists your own account aliases and effective tools.

## Not implemented

Sending mail (`messages.send`, `drafts.send`), deleting or trashing messages and drafts,
batch operations, history/watch, settings and forwarding; Drive delete, trash, sharing and
permissions; Sheets and Slides content; Calendar. Grants for these are rejected by the
policy parser.

Input schemas come from the discovery documents bundled with the locked
`google-api-python-client` version.
