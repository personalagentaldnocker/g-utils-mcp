# Operations and limits

Configuration uses environment variables; no implicit .env file is loaded.

| Name | Purpose |
| --- | --- |
| GOOGLE_CLOUD_PROJECT | ADC quota/project context |
| POLICY_URI | Fixed gs://bucket/object policy path, never a tool argument |
| TEMP_BUCKET | Durable OAuth state, artifact bytes and pagination handles |
| PUBLIC_BASE_URL | Exact HTTPS origin for host checks and Google callback |
| ALLOWED_SECRET_PROJECTS | JSON array of permitted project identifiers, e.g. ["your-project-id"] |
| PORT | Cloud Run port, default 8080 |
| MAX_TRANSFER_BYTES | Default 20,000,000; bounded to 25,000,000 |
| MAX_RESULT_BYTES | Default 1,000,000 tool-result JSON bytes |
| ARTIFACT_TTL_SECONDS | Default 1800, maximum 3600 |

/health is minimal public liveness. /ready requires a principal credential and
checks current policy readability, not all Google accounts. /mcp and /artifacts
require authentication every request. Session IDs are not credentials. OAuth routes
use their administrative intent/state checks. Access logs are disabled to keep
OAuth code/state queries out of application logs. Audit includes only safe IDs,
method, policy generation, decision, duration and error class, not payloads/tokens.
Do not enable request-body or verbose Google HTTP logging in production.

Use /health and /ready for Cloud Run. Its frontend reserves some URL paths ending
in `z`, which can return 404 before reaching the container. The legacy /healthz and
/readyz aliases remain available inside the application. See
[Cloud Run reserved URL paths](https://docs.cloud.google.com/run/docs/known-issues).

Artifacts expire at application access time, even before GCS's one-day cleanup.
No public bucket or presigned URL is issued. Active downloads/reuses recheck source
permissions; files already downloaded to a client cannot be recalled. Temporary
bucket soft-delete is disabled to avoid retaining expired transient bytes by default;
policy retains versioning/recovery. Inspect regional GCS/Run/Registry costs and set
project budget alerts through your billing administration; budgets are not hard caps.
Run scales to zero and has a configured maximum instance count.

20 MB is a byte-transfer limit, not a promise every attachment will fit Gmail.
MIME/Base64 expands size. Composed raw message limit is 30 MB; tool-result limit
may require fields/smaller pages. Large/chunked uploads beyond these limits and
watch/PubSub features are deferred. No blind retries of mutations after timeouts:
uncertain_write requires reconciliation in Gmail/Drive before trying again.

Gmail draft updates use a final read/version check but Google offers no atomic
compare-and-swap against manual Gmail edits. Docs requires expected revisions.
A policy change affects new requests, not a Google operation already running.
Runtime can access all token secrets granted to its SA: one shared service is not
hard isolation against compromised server code. Treat deployment rights as privileged.

## Recovery

- Invalid GCS policy locks calls; restore with operator gcs_policy rollback using
  the current expected generation. Runtime cannot repair its own policy.
- Invalid Google grants require auth reconnect and renewed browser consent.
- Disable account/principal or remove a grant, then diff/publish for immediate
  application revocation. Rotate credentials with a bounded overlap.
- Roll back the image through Terraform using a known previous digest. Retain
  state and configuration securely; don't grant runtime deploy permissions.
- Use Cloud Logging error/decision metrics and normal Cloud Run latency/5xx metrics
  for optional alerts; avoid logging message bodies, subject lines or credentials.

## Validation evidence

The default pytest suite tests policy/auth isolation, real HTTP MCP transport,
artifacts, wrappers with injected Google adapters, MIME edits, OAuth replay and
operator entrypoints. Terraform configurations validate against the pinned real
provider; mock-provider tests inspect the IAM/service plan. Image verification
checks the installed runtime and absence of administrative directories.

Live GCP apply, actual-account OAuth/API calls, deployed IAM permission checks,
and the real hosted Claude checklist require project configuration, usable operator
ADC, and consenting test accounts. They are not established by local tests. Current
implementation environment has no usable GCP ADC and no project/service values;
no cloud resources or permissions were changed during implementation.

Implementation validation run: **86 non-live tests passed**, one live test explicitly
excluded; Ruff check/format and mypy passed. All three Terraform roots validated,
and two mocked Terraform plan tests passed. The non-root container built using
the verified uv cache and passed CLI, health, mandatory-authentication and content
checks. The standard networked Docker dependency install was blocked by this
builder's DNS; the offline-cache path preserved verification. GitHub Actions status
could not be queried here because the GitHub API returned 403; no remote CI pass
is claimed.
