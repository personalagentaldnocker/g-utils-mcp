# Development

Use the existing checkout. uv manages Python 3.12 and the committed lockfile.
Run `uv sync --locked --all-groups`, `uv run ruff check .`,
`uv run mypy src`, and `uv run pytest -m 'not live'` before committing changes.

Architecture: authenticate MCP principal, read the current GCS policy generation,
authorize context/account/method and arguments, then load that account's OAuth
binding from Secret Manager using the Cloud Run service identity. Deny wins.
Do not weaken policy checks or silently add implemented methods to grants.
Runtime cannot write policy or IAM. Credentials must never enter Git, Terraform
state, logs, tool results, or command-line arguments. Administrative scripts are
excluded from the runtime image. Sending mail and deleting messages are outside
the first-release scope. See IMPLEMENTATION_PLAN.md and docs/ for the contract.

Live tests require explicit test-account configuration; never substitute real
production accounts for disposable fixtures. Report live validation as unrun
when deployment access is absent.

Documentation is top-down: open with the outcome and the concrete action
(file name and location, exact command, required variables). Background,
caveats and what is out of scope come after, briefly.
