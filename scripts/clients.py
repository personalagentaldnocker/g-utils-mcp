"""Generate and revoke principal credentials without printing their values."""

import hashlib
import secrets
from pathlib import Path
from typing import Annotated

import typer
from admin_common import cloud, load_policy, protected_write, save_policy

from google_utils_mcp.policy.models import Principal

app = typer.Typer(no_args_is_help=True)


@app.command()
def create(
    policy_file: Annotated[Path, typer.Option()],
    principal: Annotated[str, typer.Option()],
    owner: Annotated[str, typer.Option()],
    context: Annotated[str, typer.Option()],
    digest_ref: Annotated[str, typer.Option()],
    output: Annotated[Path, typer.Option()],
):
    policy = load_policy(policy_file)
    if principal in policy.principals:
        raise typer.BadParameter("Principal exists; use rotate")
    target = Principal(
        owner=owner, credential_digest_secret_refs=[digest_ref], allowed_contexts=[context]
    )
    policy.principals[principal] = target
    # Validate before generating credentials or changing the secret.
    type(policy).model_validate(policy.model_dump())
    token = principal + "." + secrets.token_urlsafe(32)
    protected_write(output, token.encode())
    _, _, secret_store = cloud()
    secret_store.add(digest_ref, hashlib.sha256(token.encode()).hexdigest().encode())
    save_policy(policy_file, policy)
    typer.echo("Credential saved securely. Add explicit grants, review the policy, and publish.")


@app.command()
def rotate(
    policy_file: Annotated[Path, typer.Option()],
    principal: Annotated[str, typer.Option()],
    digest_ref: Annotated[str, typer.Option()],
    output: Annotated[Path, typer.Option()],
):
    policy = load_policy(policy_file)
    target = policy.principals[principal]
    if (
        digest_ref in target.credential_digest_secret_refs
        or len(target.credential_digest_secret_refs) >= 3
    ):
        raise typer.BadParameter("Use a new secret reference; retire an old reference if necessary")
    token = principal + "." + secrets.token_urlsafe(32)
    protected_write(output, token.encode())
    _, _, secret_store = cloud()
    secret_store.add(digest_ref, hashlib.sha256(token.encode()).hexdigest().encode())
    target.credential_digest_secret_refs.append(digest_ref)
    save_policy(policy_file, policy)
    typer.echo(
        "New credential saved. Publish the overlap, switch clients, then revoke the old reference."
    )


@app.command()
def revoke(
    policy_file: Annotated[Path, typer.Option()],
    principal: Annotated[str, typer.Option()],
    digest_ref: str = "",
):
    policy = load_policy(policy_file)
    target = policy.principals[principal]
    if digest_ref:
        target.credential_digest_secret_refs.remove(digest_ref)
        if not target.credential_digest_secret_refs:
            raise typer.BadParameter(
                "Use revoke without --digest-ref to disable the entire principal"
            )
    else:
        target.enabled = False
    save_policy(policy_file, policy)


if __name__ == "__main__":
    app()
