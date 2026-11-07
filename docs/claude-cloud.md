# Claude Code on the web / cloud sessions

This release uses an explicitly configured Authorization bearer header for MCP;
it does not implement an OAuth authorization server for MCP clients. Google account consent is a separate browser flow. Actual hosted-client header network support must be verified in the target cloud session; a desktop or Python client isn't proof.

Store MCP_TOKEN securely in that session's environment. MCP_URL is the deployed
HTTPS origin. Allow that exact host through the session's network configuration.
If using a proxy-backed network secret, bind it to that hostname and use the
supported HTTPS route. It may be a placeholder rather than a raw local credential.

For a Claude Code version that supports HTTP servers and environment expansion, use the following non-secret MCP configuration (verify with that version's `claude mcp --help` and https://code.claude.com/docs/en/mcp):

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

Keep actual credential values out of .mcp.json and Git. Use the client's supported
user/project configuration location, restart/reconnect, and inspect its MCP status.
If the hosted environment does not load that configuration or inject headers,
record that as a blocker. Do not replace authentication with public access. A
supported identity provider/MCP OAuth adapter can be added as a separate mode if
needed after the hosted-client capability is established.

First run a read-only check from the same cloud session:

```bash
uv sync --locked --all-groups
uv run python scripts/smoke.py
```

This checks the official SDK's client, not Claude itself. Then invoke
workspace_capabilities through Claude and confirm account aliases and tools.
Every Google tool takes account, context and params; these select among grants,
never authenticate the caller.

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
