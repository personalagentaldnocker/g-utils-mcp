"""Operator entrypoint for initial Google consent and explicit account activation."""

import json
import secrets
import time
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from admin_common import cloud, load_policy, report, save_policy

from g_utils_mcp.storage import GCSStore

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)


@app.command()
def connect(
    account: Annotated[str, typer.Option()],
    service: Annotated[str, typer.Option()],
    open_browser: bool = True,
):
    settings, policies, _ = cloud()
    if not settings.public_base_url:
        raise typer.BadParameter("Configure PUBLIC_BASE_URL before enrollment")
    policy = policies.current().policy
    if service not in ("gmail", "drive"):
        raise typer.BadParameter("Use gmail or drive; Docs reuses the Drive identity")
    target = policy.accounts[account]
    binding = target.services[service]
    intent_id = secrets.token_urlsafe(32)
    intent = {
        "account": account,
        "service": service,
        "expected_email": target.expected_email,
        "oauth_client": binding.oauth_client,
        "target_secret": binding.refresh_token_secret_ref,
        "scopes": binding.oauth_scopes,
        "expires": time.time() + 600,
    }
    policies.objects.put("enrollments/" + intent_id, json.dumps(intent).encode())
    url = settings.public_base_url + "/oauth/google/start?intent=" + intent_id
    typer.echo("Enrollment ID: " + intent_id)
    typer.echo("Open this short-lived enrollment link in your private browser:\n" + url)
    if open_browser:
        webbrowser.open(url)


@app.command()
def status(intent: Annotated[str, typer.Option()]):
    settings, _, _ = cloud()
    report(json.loads(GCSStore(settings.temp_bucket).read("enrollments/" + intent).data))


@app.command()
def activate(intent: Annotated[str, typer.Option()], policy_file: Annotated[Path, typer.Option()]):
    settings, policies, secrets_store = cloud()
    enrollment = json.loads(policies.objects.read("enrollments/" + intent).data)
    completed = json.loads(GCSStore(settings.temp_bucket).read("enrollments/" + intent).data)
    if completed["status"] != "connected_pending_activation":
        raise typer.BadParameter("Enrollment has not completed")
    token = json.loads(secrets_store.read(enrollment["target_secret"]))
    if (
        token["google_subject"] != completed["google_subject"]
        or token["account_alias"] != enrollment["account"]
    ):
        raise typer.BadParameter("Credential binding mismatch")
    policy = load_policy(policy_file)
    account = policy.accounts[enrollment["account"]]
    binding = account.services[enrollment["service"]]
    if (
        binding.oauth_client != enrollment["oauth_client"]
        or binding.refresh_token_secret_ref != enrollment["target_secret"]
        or not set(binding.oauth_scopes).issubset(token["scopes"])
    ):
        raise typer.BadParameter("Local account binding changed; reconcile before activation")
    if account.expected_email.lower() != completed["email"].lower():
        raise typer.BadParameter("Unexpected email")
    account.google_subject = completed["google_subject"]
    account.enabled = True
    save_policy(policy_file, policy)
    typer.echo("Local account activated. Review gcs_policy.py diff, then publish separately.")


@app.command()
def reconnect(account: Annotated[str, typer.Option()], service: Annotated[str, typer.Option()]):
    connect(account, service)


if __name__ == "__main__":
    app()
