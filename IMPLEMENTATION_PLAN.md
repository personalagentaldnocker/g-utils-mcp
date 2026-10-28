# g-utils-mcp: implementation handoff for Sol

Status: implementation authorized. Core service, Terraform, operator tools and local validation are implemented; real deployment and Google/Claude live acceptance require external configuration. See docs/operations.md for evidence and limits. Local administration remains the default. Prepared 2026-10-24 against `fd8cff4` and its README. This is an implementation specification, not evidence of a deployed or tested service.

## 1. Task and decisions

Build a usable, documented Python MCP service for Gmail, Google Drive, and Google document content editing from this repository. Use **uv** for Python, the **official MCP Python SDK**, official Google Python clients, **Terraform** for infrastructure, and documented CLI commands for administration. Support multiple Google accounts and multiple agent principals with different permissions. The intended consumer is Claude running in the cloud.

The first required client is **Claude Code on the web / cloud coding sessions**, confirmed by the owner. Claude's chat-only custom connector is outside the initial acceptance scope.

The owner already has a GCP project, enabled APIs, and a Google OAuth application described as being in production. Support that existing project without replacing its configuration. Also document a complete path starting with an otherwise empty GCP project. Do not assume production OAuth status proves restricted-scope verification, valid refresh tokens, billing, or IAM readiness.

Confirmed decisions and explicit defaults:

| Decision | Owner requirement / default | Implementation approach |
| --- | --- | --- |
| Client — resolved | Claude Code on the web / cloud coding sessions. | Prove its remote MCP authentication and shell-based binary file transfer in an actual cloud session. |
| Gmail — confirmed | Query, list, read; list/edit/delete labels; add/remove/download attachments; edit threads. | Implement the concrete first-release scope below. Attachment edits apply to drafts. Thread editing means reply drafts plus labels, confirmed by the owner. |
| Drive — confirmed | Dedicated Google account, no folder restrictions; list/read/download/upload and work with/edit documents. | Account-wide resource access, with configurable principal/account/method grants. No folder-restriction engine is required for release one. |
| Document types — confirmed | Google Docs only for now. | Implement Docs v1 content editing; no Sheets or Slides editor APIs. |
| API breadth | Earlier request to consider all client methods; latest reply supplies concrete features. | Treat the concrete features as release-one requirements and retain the full catalog for expansion. Do not make all 143 Gmail/Drive methods a first-release blocker without an explicit request. |
| Administration — default | Local administration; start with the owner's accounts, including the dedicated Drive account. | Keep configurable multiple accounts/principals. Administrative identity remains separate from runtime/agent credentials. Cloud administration is not required for the first release. |

GCP project ID, region, account emails, and client names are **configuration inputs**, not blockers to implementing local code and tests. Folder IDs are optional organizational inputs, not access boundaries for the dedicated Drive account. Never invent production values. Default example region to `europe-west3`, configurable before resource creation. Ask before adding any paid external identity provider if the chosen Claude client requires one.

### Concrete first-release scope

The owner's latest feature list takes precedence over the README's example of a folder-restricted Drive account.

| Area | Required behavior and API mapping |
| --- | --- |
| Gmail search/list/read | Search using Gmail `q` syntax and optional label filters; paginate messages/threads; retrieve message headers, bodies, MIME structure and entire threads. Use `users.messages.list/get`, `users.threads.list/get`, and account profile where needed. |
| Gmail labels | List/read, create, rename/edit, and delete user labels; apply/remove labels on messages and threads. Use `users.labels.list/get/create/update/patch/delete`, `users.messages.modify`, and `users.threads.modify`. System labels have different capabilities: validate them and return clear errors. Deleting a label does not authorize deleting its messages. |
| Attachments | Download attachments from messages/drafts; add and remove specific attachments in new or existing drafts, including reply drafts. Use `users.messages.attachments.get` plus inline MIME data where applicable, and `users.drafts.list/get/create/update`. Preserve all unaffected message parts. Gmail has no independent add/remove attachment mutation endpoint. |
| Thread editing — confirmed | Support thread labels and editing reply drafts associated with a thread. Preserve `threadId`, `In-Reply-To`, `References`, recipients, and subject as appropriate. Received/sent message bodies and their attachments cannot be rewritten in place; do not emulate this by deleting and reimporting messages. |
| Drive account-wide access | Search/list metadata and files across everything accessible to the dedicated account, read metadata/content, download binary files, export Workspace files, upload new files, and update existing binary contents/metadata. Handle folders, duplicate names, pagination, and Shared Drive files when available. No configured allowed-root list is required. |
| Google document editing | Read, create, and edit actual Google Docs content through Docs v1 (`documents.get/create/batchUpdate`), with Drive handling file metadata, folders, and export. Sheets/Slides content editing is out of scope. |

Email sending, permanent message deletion, trashing messages, forwarding/settings changes, and account administration are not implied by this feature list. Keep those methods disabled in the initial policy. Allow Gmail user-label deletion as explicitly requested. Account-wide Drive access removes folder restrictions; authentication and different principals' method/account permissions still apply. Do not silently add Drive sharing/ownership/deletion tools solely because the account is dedicated. Ship an empty production policy plus a clearly documented template for this feature set, activated by the operator with real account mappings.

Current repository constraints: there is no implementation, lockfile, Terraform, or test suite. The README's linked API catalog and administration guide are missing. Its reference to an uncreated repository under `~/Projects/agent-utilities/` is stale. Replace those references with the actual documentation produced here. Existing `gmail-utils` and `drive-utils` packages are not available: reuse only if the owner supplies them and they support injected credentials safely; otherwise implement using the official clients without blocking on those packages.

## 2. Deliverables and boundaries

Deliver:

1. A locally runnable, packaged service with Streamable HTTP MCP, Google OAuth callback, authenticated binary artifact transfer, liveness, and internal readiness checks.
2. Explicit, tested policy enforcement for principal + context + Google account + API method + arguments/resources.
3. A complete pinned Gmail v1 / Drive v3 method catalog, a Docs v1 catalog, generated coverage report, and wrappers for the concrete first-release scope. No Sheets/Slides catalog is needed for this release.
4. Small Terraform configurations, safe handling of pre-existing GCP resources, and reproducible container deployment.
5. Administrative scripts for policy files in GCS, account enrollment, MCP client credentials, diagnostics, deployment, and revocation.
6. Tested setup, operations, and Claude client instructions, including a real cloud-session file-transfer walkthrough.
7. Unit/integration tests runnable without Google credentials; separately marked live tests using explicitly supplied test accounts and folders.

Do not include Calendar, a management web application, arbitrary Python/HTTP execution tools, or automated permission escalation. Google Docs content editing is now in scope: Drive alone cannot provide it. Sheets/Slides content editing is out of scope. No domain-wide delegation by default. No production migration until the test-account acceptance path succeeds.

## 3. Prove the Claude connection before building around it

Create a minimal local MCP integration fixture with one harmless tool. Use it to verify the pinned SDK's HTTP behavior. Then test a temporary deployed authenticated endpoint in the **actual selected Claude client**, once the owner supplies deployment access. A Python MCP client or desktop connection alone does not prove Claude cloud compatibility.

Record client version/product, connection configuration, authentication mode, supported HTTP behavior, network configuration, and file-transfer mechanism in `docs/claude-cloud.md`.

- For Claude Code cloud, test whether configured remote MCP servers and headers/credential helpers are honored in that specific hosted environment. If they are, a revocable high-entropy credential per agent principal is a simple initial mode. Scope any network-secret substitution to the exact service hostname. Do not assume such a placeholder is a real local secret.
- If Claude Code cloud cannot use the static-credential path but supports MCP OAuth, document the evidence and propose a supported OAuth authorization server/identity provider; implement MCP resource-server discovery, audience/issuer validation, and the required challenge behavior for that mode. Do not add an identity provider speculatively or build an ad hoc OAuth authorization server. Google Workspace refresh tokens are not MCP login tokens.
- Keep an identity-adapter boundary so static-credential and OAuth-token authentication map to the same server-side principal model. Implement only the modes required by the selected client initially.
- Use the Cloud Run HTTPS URL; no custom domain is required. Cloud Run must allow the selected clients to reach the application. Do not expect Claude to mint a Google Cloud Run IAM ID token. Application authentication protects MCP and artifact routes; Google OAuth callback/start have their own checks.
- Validate MCP POST and any GET/DELETE/SSE behavior required by the pinned SDK and client. Authenticate every request. A session ID is not authentication. Prefer stateless transport where supported; do not rely on sticky sessions or in-memory authorization state.
- Test Origin/Host validation without rejecting legitimate non-browser clients, reconnects, bounded request duration, and cancellation. Enable CORS only for a demonstrated need.
- Claude Code can use an authenticated CLI to move artifact bytes into its filesystem if its shell/network features allow it. Verify this in the web/cloud product. Chat-only custom connectors are not a first-release deliverable. Do not fall back to unauthenticated public download links.

If real Claude access is unavailable, finish independent implementation but label this acceptance test **unrun**, not passed. The client choice is an architectural gate, not an invitation to block all local development.

## 4. Architecture and repository layout

One Cloud Run service contains MCP, Google OAuth routes, and artifacts. Use separate GCS buckets for policy/enrollment intents and temporary data. Store long-lived credentials in Secret Manager. Use the assigned runtime service account through ADC; no service-account JSON key.

```text
pyproject.toml                  # package metadata, uv dependency groups, CLI entrypoints
uv.lock
.python-version                # choose/pin a supported version; 3.12 is a starting candidate
AGENTS.md                      # commands, architecture, credential and permission invariants
src/g_utils_mcp/
  app.py                       # ASGI app and routes
  mcp_server.py                # registration, discovery, dispatch
  identity.py                  # authenticated principal, no user-supplied impersonation
  config.py
  registry.py                  # method definitions, validators, capabilities
  policy/{models,store,authorize,constraints}.py
  credentials/{secrets,google_oauth}.py
  oauth/{routes,transactions}.py
  services/{gmail,drive,docs}.py
  artifacts.py
  audit.py
  errors.py
  cli.py                       # non-administrative artifact upload/download helper
scripts/
  doctor.py
  auth.py                      # initial Google-account enrollment entrypoint
  gcs_policy.py                 # pull/validate/diff/publish/history/rollback
  accounts.py
  clients.py
  secrets.py
  generate_api_catalog.py
  build.sh
  deploy.sh
  smoke.py
  verify_image.sh
infrastructure/
  bootstrap/                   # remote Terraform state bucket, if desired
  foundation/                  # APIs, registry, identities, buckets, secret shells, IAM
  service/                     # Cloud Run image/config/invoker settings
schemas/
examples/                      # fake accounts and identifiers only
discovery/                     # pinned official JSON, source URLs, revisions, SHA-256 manifest
tests/{unit,integration,live}/
docs/{setup-gcp,terraform,authentication,policy,cli,claude-cloud,operations,api-coverage}.md
Dockerfile
.dockerignore
.gcloudignore
.gitignore
```

Use uv dependency groups for development and administration. Pin tested Python, uv, MCP SDK, Terraform, and Google provider versions; commit `uv.lock` and Terraform provider lockfiles. Select SDK APIs from the pinned release's documentation: the current SDK main branch shows v2 APIs, so do not copy old FastMCP examples uncritically.

Runtime dependencies should include the official `mcp`, `google-api-python-client`, `google-auth`, `google-auth-oauthlib`, `google-cloud-storage`, and `google-cloud-secret-manager`, plus the chosen ASGI server, validation, and safe YAML libraries. Use a small CLI framework if useful. Run blocking Google clients in bounded workers; do not block the ASGI event loop or share unsafe HTTP clients between concurrent requests.

Document and make these commands work:

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run mypy src
uv run pytest -m 'not live'
uv run g-utils-mcp serve --host 127.0.0.1 --port 8080
uv run python scripts/doctor.py --local
```

Local tests use fake Google, GCS, and Secret Manager adapters. Any fake-identity development mode is loopback-only, explicit, and rejected in production configuration. Production always binds to `0.0.0.0:$PORT` and uses real authentication.

## 5. Identity, permissions, and credentials

Use the README's policy as the starting point, then tighten its schema and document semantics before implementing wrappers:

- Distinguish a human/tenant owner, an authenticated agent principal, a context, and a Google account. Two Google accounts are not two agent identities. Explicit grants relate these entities. Define whether cross-owner sharing is permitted; default to denying it.
- Support multiple Google accounts per owner and service. A principal can access only the exact account aliases and contexts granted to it. Never accept arbitrary Google user IDs or Secret Manager references from tool arguments.
- Require explicit method allow rules; deny wins. No implicit inheritance or wildcard grants. Unknown fields, duplicate YAML keys, unsupported methods, missing credentials, and invalid policy fail closed. Prevent YAML tags, alias expansion, and merge-key surprises.
- Separate capability from permission: implementing a method never enables it. Defaults and generated examples must not enable real account access.
- Make authorization order explicit: authenticate, load policy, validate principal/context/account/method/arguments, resolve bounded metadata needed for resource checks, then perform the requested action. Internal metadata reads must be authorized by a documented service capability and must not leak otherwise hidden data.
- Check the policy object's current generation for each request, download that exact generation, validate, and atomically use it. An unreadable or invalid new generation rejects new work. Cache parsed content by generation, not as an indefinite permission fallback.
- Filter `tools/list` for the principal's available capabilities. Define how discovery handles multiple contexts: an explicitly validated connection context or the union of allowed contexts, with full context/account enforcement on each call. Never imply a listed method is authorized for every account.
- Define stable safe error codes: unauthenticated, forbidden, invalid input, unavailable policy, reauthentication required, quota/rate limit, uncertain write outcome, and upstream failure. Do not reveal other accounts or secret paths in errors.
- Credentials and caches are isolated by account/service/OAuth client/secret version. Use per-account refresh coordination and verify thread safety. Never share an account-specific client globally across principals.
- For static MCP credentials, generate at least 256 random bits; persist only a digest in the server's secret. Support credential identifiers, expiry if configured, rotation overlap, and immediate revocation. Export the original credential only through an explicitly selected secure destination, not normal stdout/logs or command arguments.
- Google OAuth scopes and application grants are different. A broad Google token is not permission to use every method. Incremental consent may combine scopes for the same Google user and OAuth client; per-service configuration does not prove token isolation. Record actual granted scopes and report deviations. If strict OAuth-level isolation is required, use distinct OAuth clients and document the tradeoff.

Gmail rules: force `userId=me`; constrain label changes including TRASH/SPAM; explicitly classify sending, forwarding, filter creation, delegate changes, imports, insertion, settings, and permanent deletion. User-label deletion is an allowed first-release capability, separate from message deletion. No hidden send through a draft helper. Draft replies are the default. Preserve threading and existing attachments/recipients on partial updates. Identify attachments by stable references tied to the read draft version/MIME part, not filename alone; duplicate filenames are legal. Handle inline content IDs and nested MIME carefully when removing a part. Detect detectable concurrent changes and document Gmail's remaining non-atomic update race.

Drive rules for release one: provide an explicit account-wide resource policy for the dedicated account, without an ancestor/root allowlist or excluded folders. This covers files shared with that account as well as files it owns, subject to Google's own access checks. Isolate account credentials and grants; validate method arguments, field masks, upload/download behavior, and shortcut resolution. File updates must not silently change permissions, ownership, or trash state. A read-only principal can still be configured alongside a principal allowed to upload/edit across the same account.

Folder/subtree restrictions are a deferred extension. If implemented later, they require safe ancestry/shortcut/list/change/copy checks and concurrency documentation; do not ship a nominal `allowed_root_ids` switch with incomplete enforcement. They are not an acceptance requirement for this user's dedicated Drive account.

For lists and changes, filter before returning any unauthorized metadata, handle partial pages without leaking counts, bound scan work, and bind continuation state to principal/account/context/query/policy. Never permit a raw opaque continuation token to broaden access. Verify current resource access again when reusing artifacts or operation handles.

Google Docs editing: use the selected Drive account's authorized identity, with explicit Docs method grants. Validate the actual batch request operation types rather than granting an unrestricted `batchUpdate` payload. Provide useful helpers for reading structure, inserting/replacing/deleting text, applying basic formatting, and table editing where supported. Keep document tabs/tab IDs, structural indexes, and UTF-16 offset semantics correct. Require an expected revision for edits where the API supports it; use `writeControl.requiredRevisionId`, report conflicts, and re-read before recomputing indexes. Do not blindly retry index-based edits. Document unsupported complex elements. Validate scopes supported by both APIs; a broad Drive scope may already authorize Docs methods, so do not create unnecessary duplicate consent/token flows. Reading a Drive file through the Docs API must never switch to another account implicitly.

## 6. All API methods: inventory, implementation, and honest coverage

Interpret “all Python client methods” as the public REST methods described by Google's Discovery documents. Inventory Gmail v1, Drive v3, and the editor APIs included in scope. Transport helpers such as `execute`, `list_next`, `get_media`, resumable upload helpers, and `new_batch_http_request` are implementation mechanisms, not separate business permissions. Do not expose a generic unrestricted client dispatcher.

Planning evidence from Google's official discovery-artifact repository on 2026-10-24:

| API | Revision | Methods |
| --- | --- | ---: |
| Gmail v1 | 20261005 | 79 |
| Drive v3 | 20261011 | 64 |
| Total | | 143 |

These counts cover Gmail and Drive only, not the newly requested document editing APIs, and are a baseline rather than a permanent assertion. Re-fetch, hash, review, and pin all selected API documents during implementation. Drive includes deprecated `teamdrives` methods and specialized approvals/access-proposals/CSE/long-running operations. Gmail includes delegates, forwarding, S/MIME, and client-side encryption methods. Some cannot work for ordinary consumer accounts or require administrator-authorized credentials. Watch methods need a separate notification lifecycle and infrastructure; they are not first-release requirements.

For **every method**, generate a row containing:

- Canonical method ID, tool name, HTTP verb, Discovery revision, input/output schemas, OAuth scopes, pagination/media behavior.
- Read/write/destructive or external-delivery effects, resource constraints, account/license/admin requirements, deprecation status.
- Wrapper status (`implemented`, `planned`, `unsupported`, `requires_special_account`), validator name, test evidence, and a concrete reason for any limitation. Track those dimensions separately if a special-account wrapper is implemented but live validation is unavailable.

Generate types/schema scaffolding where useful, but write explicit method-to-validator bindings. Fail CI if a claimed implemented method lacks a validator or tests, if a newly pinned method lacks a coverage row, or if unexpected methods are registered. No `getattr` chain from user input, arbitrary discovery URL, or unrestricted endpoint override.

Implementation sequence:

1. Gmail search/profile/messages/threads, attachment download and draft add/remove, full user-label management, drafts, MIME composition, reply/reply-all drafts.
2. Account-wide Drive search/list/get/download/export/create/update and bounded upload; folder organization and Shared Drive/shortcut support where applicable.
3. Google Docs read/create/content editing, revision conflict handling, with no Sheets/Slides content editing. Steps 1–3 form the required first release.
4. Future expansion: remaining normal-account operations, with explicit policies for sends, trash/delete, sharing, settings, comments/replies/revisions, and bulk operations.
5. Future expansion: specialized/admin methods, deprecated aliases, approvals/access proposals, long-running operations, and notification methods.

Every bulk element is authorized independently; unsupported or forbidden elements fail before any write when validation can be completed first. Document partial upstream failures; a Google batch is not an atomic transaction. Large uploads, async downloads, operation polling, and watch registrations need ownership records and bounded lifetimes.

Clearly list the unimplemented methods in the first release. If the owner subsequently requires all methods for release one, finish every implementable wrapper and provide explicit capability errors plus documented account prerequisites for the remainder. Do not claim universal live coverage without the needed account classes.

## 7. Google enrollment and the initial authentication entrypoint

Implement `uv run python scripts/auth.py connect` as the documented human entrypoint. It uses the operator's local ADC/admin identity to prepare an enrollment; it does not turn an ordinary MCP credential into an administrator credential.

Flow:

1. Validate the intended account alias, expected email, service, requested scopes, configured OAuth client, callback URL, and pre-created refresh-token secret.
2. Create a short-lived enrollment intent in the policy bucket with generation preconditions. Its unguessable link is not logged; show it only as the explicit interactive authentication output or open the browser. Mark the account pending/disabled.
3. `/oauth/google/start` verifies that intent and creates state, PKCE, OIDC nonce, and a transaction in the temporary bucket. Persist everything needed across instances; prevent parallel/replayed enrollment of the same intent.
4. The browser grants Google consent using `access_type=offline` and the required identity/service scopes. Validate return parameters, issuer/audience/nonce, verified email and stable subject, exact redirect URI, and PKCE.
5. Atomically consume the transaction before code exchange. A retry after failure must not reuse an OAuth code. Limit replay, TTL, request size, and rate. Callback pages never echo codes/tokens and load no third-party content.
6. Store the refresh token and its validated binding as a new version of the pre-approved account secret. Do not overwrite a valid token with an empty refresh token. Do not store every short-lived access token in Secret Manager.
7. The admin CLI observes completion, verifies the subject/scopes, proposes the policy diff, and explicitly activates/publishes. Runtime cannot write policy or broaden its IAM.

Support `auth.py status`, `auth.py reconnect`, and documented revoke/disconnect commands. Disconnect should immediately deny new calls; remote Google-token revocation is a separate explicit operation, with documented impact on other grants sharing the same OAuth client. Handle `invalid_grant` as reauthentication required, not an infinite retry.

A Cloud Run service URL may not exist before deployment. Use this sequence: provision foundation, build/deploy a default-deny service, obtain its real HTTPS URL, register the exact Google callback URL, update service configuration, then enroll. This avoids circular Terraform inputs or fabricated URLs.

## 8. File transfer that works across machines

Implement authenticated streaming `POST /artifacts` and `GET /artifacts/{id}` plus a small uv-installable client CLI. Return opaque `file_ref`, sanitized filename, MIME type, byte count, and checksum. Never return a server filesystem path as something Claude can read locally.

- Store bytes in the temporary bucket under server-generated IDs with principal/context/account provenance and expiry metadata.
- Enforce maximum bytes while streaming, not only via Content-Length. Bound decompression and MIME parsing. Prevent path traversal, header injection, accidental overwrite in the client, and arbitrary URL/GCS imports.
- Check ownership, context, expiration, and relevant current permissions on access and reuse. Recheck source access for downloaded attachments/files when required; do not let an artifact become a way around revocation.
- Binary data stays out of model-visible JSON and logs. Include predictable cleanup and abort behavior for failed uploads.
- Start with conservative transfer limits that fit the selected Cloud Run HTTP protocol and proxy limits. The README's 20 MB attachment may expand beyond 26 MB after Base64/MIME; account for complete request/message size. Test actual limits before documenting 100 MB transfers.
- If larger transfers are required, implement bounded multipart/chunked or resumable authenticated routes with server-owned upload state. Avoid exposing public artifacts or unscoped reusable bearer URLs as a shortcut.
- In a Claude cloud acceptance run, download a test PDF to the session filesystem, upload it again, and attach it to an unsent Gmail reply draft. Verify byte checksums and the actual Gmail attachment/thread metadata.

Document response-size and tool-result budgets as well as file sizes. Large message bodies and long lists also need pagination/truncation semantics.

## 9. Terraform: keep the infrastructure small and reproducible

Use separate roots for foundation and service so the initial image/URL/OAuth bootstrap is explicit. Avoid `terraform -target` as the normal deployment workflow. Pin providers and Terraform; use `fmt`, `validate`, and plan inspection. Terraform owns each managed resource exactly once; scripts must not independently mutate the same resource configuration.

Foundation resources:

- Required project APIs only, with `disable_on_destroy = false` where supported; retain enabled services in an existing project.
- Artifact Registry Docker repository.
- Runtime service account; separate build/deploy identities only for the documented build path.
- Policy bucket: uniform bucket-level access, public-access prevention, versioning, conservative recovery settings, runtime read-only.
- Temporary bucket: uniform access, public-access prevention, runtime object CRUD only, lifecycle cleanup. Application TTL enforcement is authoritative; choose/document soft-delete settings and their cost/retention implications.
- Secret containers for OAuth client secrets, account refresh tokens, and static-client digests if used. No secret payloads or random credential values in Terraform resources/state/outputs.
- Per-secret runtime access: read client secrets and credential digests; read/add versions only for designated refresh-token secrets. No secret creation, broad project secret access, policy write, IAM mutation, or deployment permissions for runtime.
- Optional Terraform state bucket, established using a separate bootstrap procedure and migrated with `terraform init -migrate-state`. Restrict admin access; state contains sensitive infrastructure metadata even without credential payloads. Do not reuse policy or temp buckets for state.

Service resources:

- Cloud Run v2 service with an immutable image digest, runtime identity, PORT, non-secret configuration, bounded concurrency/timeouts/max instances, and a documented scale-to-zero default.
- Explicit invocation/ingress configuration compatible with the selected Claude client and browser OAuth redirects. Fail closed at application routes. Verify organization policies allow the chosen public endpoint model.
- Existing Cloud Logging integration with redaction tests. Budget alert guidance and optional low-cost uptime/error alerts; budgets are not hard spend caps.

Use additive IAM members rather than authoritative whole-project IAM policies. Never grant runtime Owner, Editor, or Secret Manager Admin. Use bucket-scoped permissions and account-specific secret bindings. Document the remaining trust boundary: code running as this one service can reach all secrets granted to its identity; application policy does not provide hard account isolation.

If watch methods are included, add their required resources as an **optional feature**: Gmail Pub/Sub topic/subscription and authenticated delivery verification, Drive webhook channel verification, renewal/expiration/stop handling, and durable ownership records. Do not deploy watch infrastructure merely to claim basic Gmail/Drive support. Notification methods remain unavailable until this feature works.

For existing resources, provide inventory and `terraform import` examples with correct addresses. Never replace buckets, OAuth clients, or service accounts just to make an apply succeed. `force_destroy` should not casually delete production policy/secrets; document teardown separately. Do not auto-import unrelated project resources.

## 10. GCP instructions and command contract

Write a complete numbered guide with two entry paths: **existing project** and **fresh project**. Clearly distinguish commands that inspect, configure, incur resources, grant access, or deploy. All commands must be copyable with documented variables and working directories. Verify exact flags against installed CLI/provider versions.

Prerequisites: Git, supported Python via uv, uv, Terraform, Google Cloud CLI, and either local Docker/buildx or a documented Cloud Build path. Explain installation using official instructions, then version checks. Prefer documented `gcloud`/Terraform functionality to handwritten REST calls. Do not add a mandatory CI identity until CI deployment is requested.

Guide sequence:

```bash
# Operator machine; substitute the owner's values.
export GCP_PROJECT_ID='your-project-id'
export GCP_REGION='europe-west3'
gcloud auth login
gcloud config set project "$GCP_PROJECT_ID"
gcloud auth application-default login
gcloud auth application-default set-quota-project "$GCP_PROJECT_ID"
gcloud services list --enabled --project "$GCP_PROJECT_ID"

uv sync --locked --all-groups
uv run python scripts/doctor.py --project "$GCP_PROJECT_ID" --region "$GCP_REGION"

terraform -chdir=infrastructure/foundation init
terraform -chdir=infrastructure/foundation plan -out=tfplan
terraform -chdir=infrastructure/foundation apply tfplan

# Implement these scripts and document their exact flags and inputs.
uv run python scripts/gcs_policy.py validate --file examples/policy.deny-all.yml
uv run python scripts/gcs_policy.py publish --file examples/policy.deny-all.yml --create
bash scripts/build.sh
terraform -chdir=infrastructure/service init
terraform -chdir=infrastructure/service plan -out=tfplan
terraform -chdir=infrastructure/service apply tfplan
```

The finished guide must explain tfvars creation and outputs passed between roots/build steps; the outline above does not supply those missing values. `build.sh` emits an image digest, not a mutable production `latest` tag. `deploy.sh` wraps plan/apply of the service root and post-deployment health checks; it does not fight Terraform with unrelated `gcloud run deploy` changes. Provide a repeatable rollback using a previously deployed digest and reviewed configuration.

Document billing linkage and project creation separately for the fresh-project path. Inspect already-enabled Gmail, Drive, Docs, Run, Artifact Registry, Secret Manager, Storage, and IAM APIs; enable only missing required APIs. Cloud Build is needed only when that build path is selected. Explain ADC versus `gcloud auth login`: one does not automatically configure all Python/Terraform credentials.

The Google OAuth web client and consent configuration may require console steps. Use Terraform or CLI only where officially supported for the chosen client type; do not invent `gcloud` commands for creating a general Google OAuth client. Provide exact console field names for audience, production/testing, scopes, redirect URI, verified domains if applicable, and consent. Production status alone is not evidence of completed Gmail/Drive restricted-scope verification or any applicable assessment. Document account-type restrictions and what must be checked for other people's accounts.

Next documented steps:

1. Register the deployed callback URL on the chosen OAuth web client.
2. Add its secret via `scripts/secrets.py` using a hidden prompt or protected input stream. Do not put credential values in shell arguments, tfvars, Git, or Terraform state.
3. Define an account and its secret container using the agreed Terraform account map; apply reviewed changes.
4. Run `uv run python scripts/auth.py connect --account ACCOUNT --service gmail` and equivalent Drive enrollment with the scopes needed for Docs editing, then verify and activate the policy. Reuse the Drive account's credential binding for Docs where the selected scopes allow it.
5. Create a principal credential or configure the chosen MCP OAuth identity provider; map it to the policy.
6. Configure the Claude client and exact network destinations; run the live acceptance guide.

`doctor.py` checks configuration presence without dumping secrets; CLI/ADC identity context, enabled APIs, required resource access, callback/config alignment, policy validity, account state, required Google scopes, and MCP connection readiness. Do not request a credential that existing ADC or a supported platform binding already provides.

## 11. The GCS policy script and other administration commands

`scripts/gcs_policy.py` is the single documented policy administration entrypoint:

| Subcommand | Required behavior |
| --- | --- |
| `pull` | Fetch policy plus generation metadata to an explicitly selected local file; avoid silently overwriting local edits. |
| `validate` | Strict schema, reference checks, method registry/capability checks, constraints and schema-version compatibility; no network needed for structural checks. |
| `diff` | Show the meaningful access changes compared with the recorded/current generation, without secret values. |
| `publish` | Validate and upload using `ifGenerationMatch`; create uses generation zero, stale edits fail. No automatic merge of grants. |
| `history` | List available policy generations with safe metadata. |
| `rollback` | Retrieve a chosen older generation, validate, display diff, publish as a new current generation using compare-and-swap. |

Keep production policies and account mappings outside Git. Use protected file permissions for local admin state. A policy snapshot is sensitive even when it contains only secret references. Make operator confirmation configurable for genuinely intentional scripted use, but never suppress a stale-generation conflict.

`accounts.py`: add/plan/status/disable/remove bindings with explicit policy diffs. `clients.py`: create/rotate/revoke credentials or identity mappings. `secrets.py`: write permitted secret payloads, show version metadata only, and manage documented rotation. Administrative scripts must not appear in MCP discovery or in the runtime image.

## 12. Tests and release acceptance

Use pytest unit tests and realistic integration fixtures, not a test suite that merely mirrors the code. No live credentials required for the default test command. Mark live tests separately and require explicit test-account/folder configuration. Default live tests do not send mail, permanently delete files, alter sharing, or change account settings. Broader method tests require a dedicated fixture environment and explicit enablement; record mock-tested versus live-tested coverage accurately.

Required test groups:

- Policy parsing, exact allow/deny semantics, context/account/tenant isolation, unknown methods, disabled accounts, adversarial parameters, and secret-reference restrictions.
- Invalid/unavailable policy and generation changes across independent server instances; concurrent admin edits and rollback.
- Multi-account concurrent execution and refresh; no credential/cache leakage.
- OAuth state/nonce/PKCE, wrong identity, replay, expiry, duplicate callbacks across instances, absent refresh token, consent rejection, `invalid_grant`, and reconnect.
- Every implemented API wrapper's allowed path, forbidden path, request transformation, resource validation, error handling, pagination/media handling, and account prerequisites.
- Gmail search and thread reads; create/edit/delete a disposable user label and apply/remove it on a test thread. Add and remove a specific draft attachment, including duplicate-filename and inline MIME cases, without losing other attachments, recipients, or reply headers; distinguish draft creation from sending.
- Drive account-wide search/read/download/upload/update, including files outside any example folder; read-only versus editing principals; Shared Drive/shortcut handling where applicable; account isolation and rejection of ungranted permission/ownership/trash changes. Folder-restriction tests are not a release-one requirement.
- Google Docs read/create/edit, structured content and tabs, UTF-16 indexes, expected-revision conflicts, and rejection of ungranted batch operation types.
- Artifact stream limits, cross-principal/context access, expiry, revocation, checksums, malformed filenames, interrupted uploads, and cleanup.
- HTTP MCP initialization/discovery/calls/reconnect, transport auth on every route, and SDK/client version compatibility.
- Structured logs contain no Authorization headers, tokens, OAuth codes, MIME bodies, or message content; container contains no admin scripts, credentials, live policies, local files, or infrastructure tooling.
- Terraform validation plus reviewed IAM plan. In the deployed test environment, verify runtime can read policy but cannot write it or change IAM/access unrelated secrets, using non-destructive permission checks where possible.
- Mutation timeout handling: do not blindly retry sends, creates, uploads, or other non-idempotent operations. Return an uncertain-outcome result and reconciliation guidance. Any supported idempotency key must use durable ownership-bound state and document Google-side limitations.

Final real-client acceptance: authenticate from the selected Claude cloud product; select each of two Google accounts with different grants; list permitted Gmail/Drive data; reject cross-account and forbidden operations; download a PDF, transfer its bytes into the session where supported, attach it to a reply draft, edit that draft, remove one attachment while preserving another, verify thread/attachments, and confirm no send occurred. Create/edit/delete a disposable label and apply/remove thread labels. Upload/download a Drive file and compare bytes; create, read, edit, and export a Google Doc, including an expected revision-conflict test. Exercise policy revocation, restart/instance changes, and reconnect. Report every unrun or unavailable-account case separately.

## 13. Milestones for Sol

1. **Decisions and compatibility:** incorporate owner answers; write brief architecture decisions; prove local MCP transport and validate the chosen cloud client's auth/file path as early as access allows.
2. **Project foundation:** uv packaging/lockfile, typed configuration, adapters, local tests, CI, strict schemas, and pinned Discovery catalog. CI does not need live secrets.
3. **Authorization and identity:** policy store, generation behavior, principal authentication, registry, constraints, and negative tests before enabling useful Google actions.
4. **Infrastructure and authentication:** Terraform foundations/service, image, deny-all deployment, GCS policy CLI, Google account enrollment, and doctor/setup guides.
5. **Working Gmail/Drive/Docs core:** tested service wrappers, artifacts and client CLI, multiple-account configuration, real test-account workflow.
6. **Coverage report:** record implemented first-release methods and deferred methods. Do not implement the optional expansion merely to fill the catalog; keep work within the confirmed feature scope.
7. **Cloud acceptance and operations:** actual Claude session, IAM/image checks, rotation/revocation/rollback, monitoring/cost notes, and complete documentation.

Implement code and local tests autonomously. Use existing checkouts; do not create worktrees merely for setup. Production identifiers and credentials go in local/environment configuration, not source. Present concrete Terraform plans and policy diffs before production mutations when execution has not already been authorized. Missing deployment access blocks live validation, not packaging, tests, scripts, or documentation. Never describe planned CLI commands as verified until they have been exercised.

Definition of done: a new developer can clone, `uv sync --locked --all-groups`, run meaningful tests, follow the GCP/Terraform guide, enroll a test account from the documented entrypoint, publish a reviewed GCS policy, configure the selected Claude cloud client, and complete the acceptance workflow. All agreed wrappers have recorded coverage; remaining external prerequisites are explicit. Updating documentation alone is not completion of this implementation task.

## 14. Official references and evidence limits

Use current official documentation and CLI `--help` for actual implementation; pin and record the versions tested.

- uv: https://docs.astral.sh/uv/
- Terraform Google provider: https://registry.terraform.io/providers/hashicorp/google/latest/docs
- GCS Terraform backend: https://developer.hashicorp.com/terraform/language/backend/gcs
- Google Cloud ADC: https://cloud.google.com/docs/authentication/provide-credentials-adc
- Cloud Run container contract: https://cloud.google.com/run/docs/container-contract
- Cloud Run public access: https://cloud.google.com/run/docs/authenticating/public
- Google web-server OAuth: https://developers.google.com/identity/protocols/oauth2/web-server
- Gmail drafts: https://developers.google.com/workspace/gmail/api/guides/drafts
- Drive API: https://developers.google.com/workspace/drive/api/guides/about-sdk
- Google Docs API: https://developers.google.com/workspace/docs/api/how-tos/overview
- Docs batch updates and revision controls: https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/batchUpdate
- GCS generation preconditions: https://cloud.google.com/storage/docs/request-preconditions
- Secret Manager IAM: https://cloud.google.com/secret-manager/docs/access-control
- Official API catalog sources inspected for this plan: https://github.com/googleapis/discovery-artifact-manager/tree/master/discoveries (`gmail.v1.json`, `drive.v3.json`).
- Official MCP Python SDK README inspected: https://github.com/modelcontextprotocol/python-sdk ; documentation: https://py.sdk.modelcontextprotocol.io/
- MCP authorization specification inspected via its official repository: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/basic/authorization.mdx
- Claude Code MCP instructions to verify: https://code.claude.com/docs/en/mcp
- Claude Code web instructions to verify: https://code.claude.com/docs/en/claude-code-on-the-web

This planning environment could read the official GitHub sources but its proxy denied direct access to the Claude documentation and several product documentation/API hosts. Consequently Claude product compatibility is not verified here. Terraform and gcloud are not installed in this planning instance; no infrastructure commands or deployments were executed. The implementation must confirm exact provider resources, CLI flags, client capabilities, and account-specific Google requirements rather than assuming the planning examples establish them.
