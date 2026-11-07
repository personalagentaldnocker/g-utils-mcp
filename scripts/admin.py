"""Operator commands, run on your laptop with your own gcloud login (ADC).

Needs POLICY_URI and SECRET_NAME (see .env.example). Not part of the runtime image.

  uv run python scripts/admin.py policy-validate --file local/policy.yml
  uv run python scripts/admin.py policy-pull --file local/policy.yml
  uv run python scripts/admin.py policy-push --file local/policy.yml
  uv run python scripts/admin.py client --file local/client_secret.json
  uv run python scripts/admin.py login --account mailbox
  uv run python scripts/admin.py token --principal claude-cloud --output local/mcp-token
"""

import json
import os
import secrets
from pathlib import Path
from typing import Annotated

import typer

from g_utils_mcp import config
from g_utils_mcp.utils import auth, helpers

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
File = Annotated[Path, typer.Option()]


def write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)


def generation_file(path: Path) -> Path:
    return Path(str(path) + ".generation")


@app.command("policy-validate")
def policy_validate(file: File):
    """Check a local policy file."""
    auth.parse_policy(file.read_bytes())
    typer.echo("valid")


@app.command("policy-pull")
def policy_pull(file: File):
    """Download the policy and remember its generation for the next push."""
    data, generation = helpers.gcs_read(config.policy_uri())
    write_private(file, data)
    write_private(generation_file(file), str(generation).encode())
    typer.echo(f"pulled generation {generation}")


@app.command("policy-push")
def policy_push(file: File):
    """Upload the policy; fails if it changed since your pull (or exists, without a pull)."""
    auth.parse_policy(file.read_bytes())
    sidecar = generation_file(file)
    expected = int(sidecar.read_text()) if sidecar.exists() else 0
    generation = helpers.gcs_write(config.policy_uri(), file.read_bytes(), expected)
    write_private(sidecar, str(generation).encode())
    typer.echo(f"pushed generation {generation}")


@app.command()
def client(file: File):
    """Store the Desktop OAuth client (JSON downloaded from the Cloud Console) in the secret."""
    installed = json.loads(file.read_text())["installed"]
    secret = helpers.secret_read(config.secret_name())
    secret["oauth_client"] = {
        "client_id": installed["client_id"],
        "client_secret": installed["client_secret"],
    }
    helpers.secret_write(config.secret_name(), secret)
    typer.echo("OAuth client stored; you can delete the downloaded JSON")


@app.command()
def login(account: Annotated[str, typer.Option()]):
    """Sign a policy account in through the browser and store its refresh token."""
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token
    from google_auth_oauthlib.flow import InstalledAppFlow

    policy = auth.current_policy(config.policy_uri())
    if account not in policy.accounts:
        raise typer.BadParameter(f"Account {account!r} is not in the policy")
    target = policy.accounts[account]
    secret = helpers.secret_read(config.secret_name())
    if "oauth_client" not in secret:
        raise typer.BadParameter("Run the `client` command first")
    client_config = {
        "installed": {
            **secret["oauth_client"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    scopes = auth.scopes_for(target.services)
    typer.echo(f"Sign in as {target.expected_email} in the browser window.")
    flow = InstalledAppFlow.from_client_config(client_config, scopes)
    creds = flow.run_local_server(port=0, login_hint=target.expected_email, prompt="consent")
    claims = id_token.verify_oauth2_token(
        creds.id_token, Request(), secret["oauth_client"]["client_id"]
    )
    email = str(claims.get("email", ""))
    if not claims.get("email_verified") or email.lower() != target.expected_email.lower():
        raise typer.BadParameter(
            f"Signed in as {email}, expected {target.expected_email}; nothing stored"
        )
    if not creds.refresh_token or not set(scopes) <= set(creds.granted_scopes or scopes):
        raise typer.BadParameter("Google returned no refresh token or fewer scopes; nothing stored")
    secret = helpers.secret_read(config.secret_name())  # re-read right before writing
    secret.setdefault("accounts", {})[account] = {
        "email": email,
        "subject": claims["sub"],
        "refresh_token": creds.refresh_token,
        "scopes": scopes,
    }
    helpers.secret_write(config.secret_name(), secret)
    typer.echo(f"{account} signed in as {email}. Set enabled: true in the policy and push it.")


@app.command()
def token(
    principal: Annotated[str, typer.Option()],
    output: File,
    new: Annotated[
        bool, typer.Option(help="Replace the token (the old one stops working)")
    ] = False,
):
    """Write the principal's MCP token to a private file, creating it if needed."""
    secret = helpers.secret_read(config.secret_name())
    entry = secret.setdefault("principals", {}).setdefault(principal, {})
    if new or not entry.get("token"):
        entry["token"] = secrets.token_urlsafe(32)
        helpers.secret_write(config.secret_name(), secret)
    write_private(output, entry["token"].encode())
    typer.echo(f"Token written to {output} (mode 600). Use it as MCP_TOKEN.")


if __name__ == "__main__":
    app()
