"""Check local prerequisites or configured cloud access without exposing credentials."""

import importlib.metadata
import json
import shutil

import typer

app = typer.Typer(pretty_exceptions_show_locals=False)


@app.command()
def main(local: bool = False, project: str = "", region: str = "europe-west3"):
    checks = {"python_packages": {}, "commands": {}, "cloud": "not requested"}
    for package in (
        "mcp",
        "google-api-python-client",
        "google-auth",
        "google-cloud-storage",
        "google-cloud-secret-manager",
    ):
        checks["python_packages"][package] = importlib.metadata.version(package)
    for command in ("uv", "terraform", "gcloud", "docker"):
        checks["commands"][command] = bool(shutil.which(command))
    if not local:
        from admin_common import cloud

        try:
            settings, policies, _ = cloud()
            snapshot = policies.current()
            checks["cloud"] = {
                "policy_readable": True,
                "generation": snapshot.generation,
                "accounts": {
                    k: {"enabled": v.enabled, "identity_verified": bool(v.google_subject)}
                    for k, v in snapshot.policy.accounts.items()
                },
                "project_configured": bool(project or settings.google_cloud_project),
                "callback_configured": bool(settings.public_base_url),
            }
        except Exception:
            checks["cloud"] = {
                "ready": False,
                "action": "Check ADC, POLICY_URI, project, resources and IAM",
            }
            typer.echo(json.dumps(checks, indent=2))
            raise typer.Exit(1) from None
    typer.echo(json.dumps(checks, indent=2))


if __name__ == "__main__":
    app()
