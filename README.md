# g-utils

Python HTTP MCP for Gmail, Drive, and Google Docs on Cloud Run.

**Authenticate agent → read current GCS policy → authorize context/account/method
and arguments → load that account's OAuth binding from Secret Manager using the
Cloud Run service account → execute the Google wrapper.** Runtime cannot edit policy.

Multiple Google accounts and multiple agent principals can have different grants.
Gmail supports search/read, user labels, thread labels, reply drafts, and attachment
add/remove/download. Drive supports account-wide file search/read/upload/download/
update/export; Docs supports content edits with revision checks. Binary files move
through authenticated artifacts, without Base64 through the model context.

Mail sending/deletion, Drive sharing/deletion, Calendar, Sheets/Slides editing,
folder restrictions, and specialist/admin API methods are deferred. See the
[complete API coverage](docs/api-coverage.md) for every exposed/deferred method.

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run mypy src
uv run pytest -m 'not live'
uv run python scripts/doctor.py --local
```

Offline tests inject in-memory adapters; production has no fake authentication mode.
For the real configured service: `uv run g-utils serve`.

Follow these guides in order:

1. [GCP setup, existing/fresh project](docs/setup-gcp.md)
2. [Terraform, imports, build and deployment](docs/terraform.md)
3. [Initial Google authentication and agent credentials](docs/authentication.md)
4. [GCS permissions file](docs/policy.md)
5. [Operator commands](docs/cli.md)
6. [Claude Code cloud and acceptance checks](docs/claude-cloud.md)
7. [Operations, limits and validation status](docs/operations.md)

Start with [deny-all](examples/policy.deny-all.yml). The [feature template](examples/policy.example.yml)
uses fake identifiers and disabled accounts. Replace them locally, enroll, then
activate. Keep production policies/credentials in ignored `local/` or secure stores.
The [implementation plan](IMPLEMENTATION_PLAN.md) records the agreed scope.
