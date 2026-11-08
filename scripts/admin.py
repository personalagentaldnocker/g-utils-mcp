"""Operator commands, run on the operator's laptop with their own ADC. Not in the runtime image.

uv run python scripts/admin.py --help
"""

import difflib
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Annotated

import typer
import yaml

from g_utils_mcp import policy as pol
from g_utils_mcp.app import KNOWN
from g_utils_mcp.utils import SECRET_REF

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
policy_app = typer.Typer(no_args_is_help=True, help="Validate, pull and publish the policy.")
token_app = typer.Typer(no_args_is_help=True, help="Create MCP client tokens.")
app.add_typer(policy_app, name="policy")
app.add_typer(token_app, name="token")
IDENTITY_SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]
# v1 helper tools were visible when any of these methods was allowed. v2 lists them by name.
V1_HELPERS = {
    "gmail_attachment_download": {"gmail.users.messages.get"},
    "gmail_draft_compose": {"gmail.users.drafts.create", "gmail.users.drafts.update"},
    "drive_upload": {"drive.files.create", "drive.files.update"},
    "drive_download": {"drive.files.get"},
}


def load(file: Path) -> dict:
    return pol.parse(file.read_bytes(), KNOWN)


def dump(policy: dict) -> bytes:
    return yaml.safe_dump(policy, sort_keys=False, allow_unicode=True).encode()


def write_private(path: Path, data: bytes) -> None:
    """Create a new 0600 file; never overwrite an existing one."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data)


def policy_blob(generation: int | None = None):
    from google.cloud import storage  # type: ignore[attr-defined]

    uri = os.environ.get("POLICY_URI", "")
    if not uri.startswith("gs://") or "/" not in uri[5:]:
        raise typer.BadParameter("Set POLICY_URI=gs://bucket/object")
    name, key = uri[5:].split("/", 1)
    return storage.Client().bucket(name).blob(key, generation=generation)


def secret_client():
    from google.cloud import secretmanager

    return secretmanager.SecretManagerServiceClient()


def read_secret(ref: str) -> bytes:
    return bytes(secret_client().access_secret_version(name=ref).payload.data)


def add_secret_version(ref: str, payload: bytes) -> None:
    parent = ref.rsplit("/versions/", 1)[0]
    secret_client().add_secret_version(request={"parent": parent, "payload": {"data": payload}})


def confirm(question: str, yes: bool) -> None:
    if not yes and not typer.confirm(question):
        raise typer.Exit(1)


# --- policy ------------------------------------------------------------------------------------


@policy_app.command("validate")
def policy_validate(file: Path):
    """Check a local policy file."""
    load(file)
    typer.echo("valid")


@policy_app.command("pull")
def policy_pull(file: Path, generation: Annotated[int | None, typer.Option()] = None):
    """Download the published policy (or an older --generation) to a new local file."""
    blob = policy_blob(generation)
    blob.reload()
    data = blob.download_as_bytes()
    write_private(file, data)
    typer.echo(f"generation {blob.generation} -> {file}")
    try:
        pol.parse(data, KNOWN)
    except ValueError as exc:  # e.g. a v1 policy pulled for `migrate`
        typer.echo(f"warning: not a valid v2 policy: {exc}", err=True)


@policy_app.command("history")
def policy_history():
    """List published generations (needs object versioning on the policy bucket)."""
    blob = policy_blob()
    for old in blob.bucket.list_blobs(prefix=blob.name, versions=True):
        if old.name == blob.name:
            typer.echo(f"{old.generation}  {old.updated}")


@policy_app.command("publish")
def policy_publish(file: Path, yes: bool = False):
    """Show the diff against the published policy, then publish if nothing changed meanwhile."""
    new = file.read_bytes()
    load(file)
    blob = policy_blob()
    exists = blob.exists()
    if exists:
        blob.reload()
        old = blob.download_as_bytes(if_generation_match=blob.generation).decode()
    else:
        old = ""
    diff = difflib.unified_diff(
        old.splitlines(True), new.decode().splitlines(True), "published", str(file)
    )
    text = "".join(diff)
    if not text:
        typer.echo("No changes.")
        return
    typer.echo(text)
    confirm("Publish this policy?", yes)
    generation = int(blob.generation) if exists else 0
    blob.upload_from_string(new, content_type="application/yaml", if_generation_match=generation)
    typer.echo(f"published generation {blob.generation}")


# --- tokens ------------------------------------------------------------------------------------


@token_app.command("new")
def token_new(
    principal: str,
    policy_file: Annotated[Path, typer.Option()],
    output: Annotated[Path, typer.Option(help="New file that receives the token (0600)")],
):
    """Create a client token, write it to --output and add its digest to the local policy."""
    policy = load(policy_file)
    entry = policy["principals"].setdefault(principal, {"token_sha256": []})
    if len(entry["token_sha256"]) >= 3:
        raise typer.BadParameter("Remove an old digest first (at most 3 during rotation)")
    token = principal + "." + secrets.token_urlsafe(32)
    write_private(output, token.encode())
    entry["token_sha256"].append(hashlib.sha256(token.encode()).hexdigest())
    policy_file.write_bytes(dump(policy))
    load(policy_file)
    typer.echo(f"Token written to {output}. Digest added to {policy_file}; publish to activate.")


# --- Google sign-in ----------------------------------------------------------------------------


@app.command()
def connect(
    account: str,
    policy_file: Annotated[Path, typer.Option()],
    client_secrets: Annotated[Path, typer.Option(help="OAuth desktop client JSON")],
    scope: Annotated[list[str], typer.Option(help="Google scope; repeat for several")],
    yes: bool = False,
):
    """Sign in to Google in a local browser and store the refresh token in Secret Manager.

    The account's email and secret come from the local policy file. The token goes straight
    from memory to Secret Manager and is never printed or written to disk.
    """
    from google.auth import jwt
    from google_auth_oauthlib.flow import InstalledAppFlow

    target = load(policy_file)["accounts"].get(account)
    if target is None:
        raise typer.BadParameter(f"Add account {account} to {policy_file} first")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secrets), scopes=sorted(set(scope) | set(IDENTITY_SCOPES))
    )
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    email = jwt.decode(creds.id_token, verify=False).get("email", "")
    if email.lower() != target["email"].lower():
        raise typer.BadParameter(f"Signed in as {email}, expected {target['email']}")
    if not creds.refresh_token:
        raise typer.BadParameter("Google returned no refresh token; revoke access and retry")
    payload = {
        "account": account,
        "email": email,
        "refresh_token": creds.refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "token_uri": creds.token_uri,
        "scopes": sorted(creds.scopes or []),
    }
    confirm(f"Store a new version of {target['secret']}?", yes)
    add_secret_version(target["secret"], json.dumps(payload).encode())
    typer.echo(f"Connected {account} ({email}).")


# --- migration from policy v1 ------------------------------------------------------------------


def migrate_policy(v1: dict, read=read_secret) -> tuple[dict, list[str]]:
    """Convert a v1 policy to v2, keeping each principal's effective permissions.

    Returns (policy, notes). Contexts are merged; deny entries from any context apply.
    """
    notes: list[str] = []
    principals = {
        name: {
            "token_sha256": [read(r).decode().strip() for r in p["credential_digest_secret_refs"]]
        }
        for name, p in v1.get("principals", {}).items()
        if p.get("enabled", True)
    }
    accounts = {}
    for name, a in v1.get("accounts", {}).items():
        if not a.get("enabled", False):
            notes.append(f"account {name} is disabled in v1 and was left out")
            continue
        refs = {b["refresh_token_secret_ref"] for b in a["services"].values()}
        if len(refs) != 1:
            raise ValueError(f"account {name} uses several token secrets; split it first")
        accounts[name] = {"email": a["expected_email"], "secret": refs.pop()}
    grants: dict[str, dict] = {}
    for context_name, context in v1.get("contexts", {}).items():
        for principal, by_account in context.get("grants", {}).items():
            p = v1["principals"].get(principal, {})
            if principal not in principals or context_name not in p.get("allowed_contexts", []):
                continue
            for account, grant in by_account.items():
                if account not in accounts:
                    continue
                if grant.get("constraints"):
                    notes.append(f"{principal}/{account}: constraints are fixed in code in v2")
                entry = grants.setdefault(principal, {}).setdefault(
                    account, {"allow": set(), "deny": set()}
                )
                allowed = set(grant.get("allow", [])) - set(grant.get("deny", []))
                entry["allow"] |= {pol.tool_name(m) for m in grant.get("allow", [])}
                entry["deny"] |= {pol.tool_name(m) for m in grant.get("deny", [])}
                for helper, methods in V1_HELPERS.items():
                    if allowed & methods:
                        entry["allow"].add(helper)
    for principal, by_account in grants.items():
        for account, entry in by_account.items():
            both = entry["allow"] & entry["deny"]
            if both:
                notes.append(f"{principal}/{account}: denied in some context: {sorted(both)}")
            by_account[account] = {"allow": sorted(entry["allow"]), "deny": sorted(entry["deny"])}
    policy = {
        "version": 2,
        "revision": str(v1.get("policy_revision", "migrated")) + "-v2",
        "principals": principals,
        "accounts": accounts,
        "grants": grants,
    }
    return policy, notes


def migrate_secret(v1: dict, account: str, read=read_secret) -> bytes:
    """Rebuild an account's token secret as authorized-user JSON.

    The old keys stay in the payload, so the currently deployed v1 runtime keeps working
    with the new secret version until the v2 image is rolled out.
    """
    a = v1["accounts"][account]
    binding = next(iter(a["services"].values()))
    client = v1["oauth_clients"][binding["oauth_client"]]
    old = json.loads(read(binding["refresh_token_secret_ref"]))
    payload = {
        **old,
        "account": account,
        "email": a["expected_email"],
        "client_id": client["client_id"],
        "client_secret": read(client["client_secret_ref"]).decode(),
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return json.dumps(payload).encode()


@app.command()
def migrate(
    v1_file: Path,
    output: Path,
    rewrite_secrets: bool = False,
    yes: bool = False,
):
    """Convert a v1 policy file to v2 (reads digest secrets with your ADC).

    With --rewrite-secrets, also add an authorized-user version to each account's token secret.
    """
    v1 = yaml.safe_load(v1_file.read_bytes())
    policy, notes = migrate_policy(v1)
    data = dump(policy)
    pol.parse(data, KNOWN)
    write_private(output, data)
    for note in notes:
        typer.echo("note: " + note, err=True)
    typer.echo(f"wrote {output}; review it, then: admin.py policy publish {output}")
    if rewrite_secrets:
        for account in policy["accounts"]:
            ref = policy["accounts"][account]["secret"]
            if not re.fullmatch(SECRET_REF, ref):
                raise typer.BadParameter("Invalid secret reference")
            confirm(f"Add an authorized-user version to {ref}?", yes)
            add_secret_version(ref, migrate_secret(v1, account))
            typer.echo(f"rewrote secret for {account}")


if __name__ == "__main__":
    sys.exit(app())
