# Use as an MCP server in Claude Code

1. `.mcp.json` in the repository root registers the server (already committed):

   ```json
   {
     "mcpServers": {
       "g-utils-mcp": {
         "type": "http",
         "url": "${MCP_URL}/mcp",
         "headers": {"Authorization": "Bearer ${MCP_TOKEN}"}
       }
     }
   }
   ```

2. Make `MCP_URL` and `MCP_TOKEN` available where Claude Code runs:
   - **Cloud session:** add both as environment variables in the cloud
     environment's settings, and allow the Cloud Run host in its network settings.
   - **Local:** export both in the shell that starts `claude`.

   `MCP_URL` is the service URL (no trailing slash). `MCP_TOKEN` is the contents
   of `local/mcp-token` from `clients.py initialize` (authentication.md). Never
   put the token value in `.mcp.json` or Git.

3. Start a new session and run `/mcp`; `g-utils-mcp` should be connected.

Prerequisite: deployment with `PUBLIC_BASE_URL`, activated accounts and the
agent token (authentication.md).

To check the connection outside Claude:

```bash
uv run python scripts/smoke.py
```

## Calling the tools

Call `workspace_capabilities` first to list account aliases and tools. Every
Google tool takes `account`, `context` and `params`; these select among grants,
they do not authenticate the caller.

Example Gmail search arguments for gmail_users_messages_list:

```json
{"account":"mailbox","context":"private","params":{"userId":"me","q":"has:attachment filename:pdf","maxResults":10}}
```

Read a message/thread, then use gmail_attachment_download with message_id/part_id
for inline or external attachments. The result has file_ref and checksum. Use the
file client to download bytes into Claude's filesystem, or pass that file_ref to a
draft composer directly. Local paths never refer to the Cloud Run filesystem.

For an existing draft, gmail_users_drafts_get returns revision, message_id and
attachment_ref values. Supply expected_revision to gmail_draft_compose, along with
text/html/to/cc/subject changes, add_file_refs or remove_attachment_refs. For a new
reply draft supply reply_to_message_id (optional reply_all); the server derives
thread/reply headers. No send tool exists.

Drive: drive_files_list supports Drive q and fields; drive_download produces an
artifact, drive_upload consumes one. Google Docs creation uses docs_documents_create;
read with docs_documents_get including includeTabsContent when needed, then edit
with docs_documents_batchUpdate and writeControl.requiredRevisionId. Use correct
tab IDs and UTF-16 indexes. Export a Doc via drive_download (PDF by default).

## Real-session acceptance checklist

Use disposable fixtures, never unsolicited messages or production changes:

1. Record Claude product/version, MCP config, host allowlist, authentication mode,
   protocol behavior, deployment digest and policy generation.
2. Check two Google account aliases and two principals with different grants;
   reject ungranted accounts/methods/context changes.
3. Search/read Gmail, create/edit/delete a disposable user label and change thread labels.
4. Download a PDF, compare its checksum locally, upload bytes, attach it to a reply
   draft, edit text, remove just one attachment and preserve another plus thread headers.
   Confirm the draft remains unsent.
5. Upload/read/download a disposable Drive file across the dedicated account;
   compare bytes. Create/read/edit/export a Google Doc; verify revision conflict rejection.
6. Revoke a grant and confirm the tool and its existing artifacts stop working.
   Restart/reconnect the service and complete another enrollment across instances.
7. Record passed/failed/unrun steps and fixture cleanup. Folder restrictions,
   specialized methods and mail sending are outside the acceptance scope.

Actual Claude cloud compatibility and Google live behavior remain unverified until
this checklist is run with a real deployment and consenting test accounts.
