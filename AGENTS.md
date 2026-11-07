# Development

Use the existing checkout. uv manages Python 3.12 and the committed lockfile.
Run `uv sync --locked --all-groups`, `uv run ruff check .`,
`uv run mypy src`, and `uv run pytest` before committing changes.

Architecture: check the GCS policy generation, authenticate the MCP token against
the single secret, authorize context/account/method and arguments, then build that
account's Google credentials from the secret using the Cloud Run identity. Deny wins.
Do not weaken policy checks or silently add implemented methods to grants.
Runtime cannot write policy, secrets or IAM. Credentials must never enter Git,
Terraform state, logs, tool results, or command-line arguments. Sign-in runs on the
operator's laptop (scripts/admin.py), which is excluded from the runtime image.
Sending mail and deleting messages are out of scope. See plan.md for decisions.
Prefer functions over classes; less is more.

Tests are offline (fake Google client). Never use real accounts as fixtures.
Report live validation as unrun when deployment access is absent.
