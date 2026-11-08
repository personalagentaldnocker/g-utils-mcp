# g-utils-mcp

A small MCP server on Cloud Run that lets an agent (Claude Code on the web) use Gmail,
Google Drive and Google Docs, limited by a permission file you control.

```text
client ──Bearer token──▶ /mcp ─▶ policy: which principal? which account? which tool? (deny wins)
                                     │  re-read only when the GCS object generation changed
                                     ▼
                         Secret Manager: that account's refresh token ─▶ Google API
```

- **Policy** (`gs://…/policies/g-utils-mcp-v2.yml`): maps token digests to principals,
  and each principal to the accounts and tool names it may use. See [docs/policy.md](docs/policy.md).
- **Google sign-in** happens on the operator's laptop (`scripts/admin.py connect`). The
  server never runs an OAuth flow and cannot write policy, secrets or IAM.
- **Tools** are Google methods named like `gmail_users_messages_list`, plus helpers for
  draft composition and file transfer. Sending mail and deleting messages are not
  implemented. See [docs/api-coverage.md](docs/api-coverage.md).

## Code

| Path | Contents |
| --- | --- |
| `src/g_utils_mcp/app.py` | MCP server, tool list and dispatch, HTTP routes, bearer auth |
| `src/g_utils_mcp/policy.py` | Policy parsing, generation-checked cache, the permission check, argument rules, `run()` (the only path to Google) |
| `src/g_utils_mcp/gmail.py`, `drive.py` | Tools that need custom code (drafts, attachments, upload/download) |
| `src/g_utils_mcp/utils.py` | Cloud Storage, Secret Manager, credentials, generic Google method call, logging |
| `src/g_utils_mcp/cli.py` | `g-utils-mcp serve`, `upload`, `download` |
| `scripts/admin.py` | Operator commands (policy, tokens, Google sign-in, v1 migration); not in the image |
| `infrastructure/` | Terraform: optional state bucket, foundation, Cloud Run service |

## Development

```bash
uv sync --locked --all-groups
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest -m 'not live'
```

Tests use in-memory fakes for Google, Cloud Storage and Secret Manager; production has no
fake mode.

## Documentation

1. [Setup: GCP, Terraform, sign-in, first deploy](docs/setup.md)
2. [Policy file](docs/policy.md)
3. [Using it from Claude Code](docs/claude-cloud.md)
4. [Operations, limits, migration from v1](docs/operations.md)
5. [Terraform details](docs/terraform.md)
6. [Tool list](docs/api-coverage.md)

[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) records the design contract and decisions.
