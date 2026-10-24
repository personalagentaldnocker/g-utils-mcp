# GCS permissions file

The GCS file is the authorization source of truth, protected by bucket IAM.
Runtime reads the current object generation on every HTTP request. It downloads
that exact generation and parses strictly. Missing/unreadable/invalid policy rejects
work; there is no indefinite fallback to an older valid policy. One MCP call uses
one snapshot. Already-running Google requests cannot be recalled by a later edit.

Policy schema: schemas/policy.schema.json. Actual feature example:
examples/policy.example.yml. This implementation uses a flat canonical method list
per principal/context/account grant, rather than nesting methods under services as
in the original planning README. For example:

```yaml
contexts:
  private:
    grants:
      claude-cloud:
        mailbox:
          allow:
            - gmail.users.messages.list
            - gmail.users.messages.get
            - gmail.users.drafts.get
            - gmail.users.drafts.update
          deny:
            - gmail.users.messages.send
          constraints:
            forbidden_added_label_ids: [TRASH, SPAM]
```

Owners group accounts and agent principals. Principals specify one to three digest
secret refs and allowed contexts. Accounts bind expected email, verified Google
subject and gmail/drive credentials. Docs uses the drive binding. OAuth clients
hold a client ID and secret ref. No values belong in the policy. Valid aliases
contain letters, numbers, underscore or hyphen (up to 80 chars).

An enabled principal, allowed context, enabled same-owner account, configured
service, exact allow, and absence of deny are all required. Deny wins; no wildcards,
inheritance or context merging. Methods require their own implemented validators.
The admin CLI rejects grants for deferred methods. Discovery is filtered per
principal across its contexts; each call rechecks its chosen context and account.
Capabilities never reveal other principals' accounts or secret references.

YAML duplicate/non-string/merge keys, aliases, anchors, tags, unknown fields and
bad references are rejected. Secret references must use the deployment's allowed
projects and are further limited by actual per-secret IAM. Runtime cannot create
secrets, grant IAM or publish policy. One shared service can access all tokens its
SA can read; application policy is not hard isolation against malicious server code.

Gmail always uses userId=me. User-label deletion is separate from message deletion;
TRASH/SPAM additions are blocked by default, including thread modifications.
Draft editing requires the unchanged revision returned by draft get; removing
attachments uses revision-bound MIME-part refs, not filenames. Existing body parts,
recipients, and thread headers are preserved unless explicitly changed. Gmail has
no atomic draft CAS, leaving a documented race after the final re-read.

Drive's dedicated account has account-wide visibility, including files shared with
it. Method grants still control edits. Upload/update can change permitted content,
name, description and MIME metadata; they cannot silently trash/share/transfer
ownership. Folder ancestry restrictions are deliberately unsupported.

Docs batch edits require writeControl.requiredRevisionId. The policy constraints
allow only known text/format/table operations. Google validates structural indexes;
clients must handle UTF-16 positions and tab IDs. Re-read after conflicts; don't
blindly replay index-based edits. Sheets/Slides content editing isn't exposed.

Page tokens are server-owned expiring handles bound to principal, context, account,
method, query and policy generation. Re-read the first page after policy changes.
Downloaded artifacts recheck policy and current source access on reuse/download;
source-method revocation invalidates them even before their TTL expires.

Policy edits use gcs_policy.py pull/diff/publish. The pull writes a .generation
sidecar. Publication uses ifGenerationMatch and rejects stale edits. Resolve a
conflict by pulling to a new file and comparing; never force an old grant over a
newer one. Rollback revalidates an older generation and publishes it as a new one.
