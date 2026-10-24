"""Edit local account bindings; policy publication is a separate reviewed step."""

from pathlib import Path
from typing import Annotated

import typer
from admin_common import load_policy, report, save_policy

from google_utils_mcp.policy.models import Account, ServiceBinding

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)


@app.command()
def add(
    policy_file: Annotated[Path, typer.Option()],
    account: Annotated[str, typer.Option()],
    owner: Annotated[str, typer.Option()],
    email: Annotated[str, typer.Option()],
    service: Annotated[str, typer.Option()],
    oauth_client: Annotated[str, typer.Option()],
    token_ref: Annotated[str, typer.Option()],
    scope: Annotated[list[str], typer.Option()],
):
    policy = load_policy(policy_file)
    if service not in ("gmail", "drive"):
        raise typer.BadParameter("Service must be gmail or drive")
    target = policy.accounts.get(account)
    if target is None:
        target = Account(owner=owner, expected_email=email, services={})
        policy.accounts[account] = target
    if target.owner != owner or target.expected_email != email:
        raise typer.BadParameter("Use a new alias for a different identity")
    target.enabled = False
    target.services[service] = ServiceBinding(
        oauth_client=oauth_client, refresh_token_secret_ref=token_ref, oauth_scopes=scope
    )
    save_policy(policy_file, policy)


@app.command()
def status(policy_file: Annotated[Path, typer.Option()]):
    policy = load_policy(policy_file)
    report(
        {
            alias: {
                "enabled": a.enabled,
                "identity_verified": bool(a.google_subject),
                "services": list(a.services),
            }
            for alias, a in policy.accounts.items()
        }
    )


@app.command()
def disable(policy_file: Annotated[Path, typer.Option()], account: Annotated[str, typer.Option()]):
    policy = load_policy(policy_file)
    policy.accounts[account].enabled = False
    save_policy(policy_file, policy)


@app.command()
def remove(policy_file: Annotated[Path, typer.Option()], account: Annotated[str, typer.Option()]):
    policy = load_policy(policy_file)
    del policy.accounts[account]
    for context in policy.contexts.values():
        for grants in context.grants.values():
            grants.pop(account, None)
    save_policy(policy_file, policy)


@app.command()
def revoke_google(
    policy_file: Annotated[Path, typer.Option()],
    account: Annotated[str, typer.Option()],
    service: Annotated[str, typer.Option()],
    yes: bool = False,
):
    """Explicitly revoke Google consent; may affect other grants on the same OAuth client."""
    import json

    import httpx
    from admin_common import cloud

    if not yes:
        typer.confirm(
            "Revoke Google consent? This may affect other tokens for this user/client.", abort=True
        )
    policy = load_policy(policy_file)
    binding = policy.accounts[account].services[service]
    _, _, secrets_store = cloud()
    token = json.loads(secrets_store.read(binding.refresh_token_secret_ref))["refresh_token"]
    response = httpx.post("https://oauth2.googleapis.com/revoke", data={"token": token}, timeout=30)
    if response.status_code != 200:
        raise typer.BadParameter("Google revocation failed; disable the account policy immediately")
    disable(policy_file, account)
    typer.echo("Google revocation succeeded. Publish the local disabled account policy.")


if __name__ == "__main__":
    app()
