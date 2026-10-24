import hashlib
import json
import os
from pathlib import Path

import httpx
import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def serve(host: str = "0.0.0.0", port: int = 0):
    """Run the authenticated Cloud Run application."""
    import uvicorn

    from .app import create_app
    from .config import Settings
    settings = Settings()
    uvicorn.run(create_app(settings), host=host, port=port or settings.port, access_log=False)


def headers(context: str) -> dict:
    token = os.environ.get("MCP_TOKEN")
    if not token:
        raise typer.BadParameter("Set MCP_TOKEN securely in the client environment")
    return {"Authorization": "Bearer " + token, "X-Workspace-Context": context}


def base_url() -> str:
    url = os.environ.get("MCP_URL", "").rstrip("/")
    if not url.startswith("https://"):
        raise typer.BadParameter("Set MCP_URL to the HTTPS service origin")
    return url


@app.command()
def upload(file: Path, context: str):
    """Upload binary bytes without placing them in the model context."""
    import mimetypes
    hdr = headers(context)
    hdr["X-Filename"] = file.name
    hdr["Content-Type"] = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    with file.open("rb") as source, httpx.Client(timeout=120) as client:
        response = client.post(base_url() + "/artifacts", headers=hdr, content=source)
    if response.status_code != 201:
        raise typer.BadParameter(f"Upload failed: HTTP {response.status_code}")
    typer.echo(json.dumps(response.json()))


@app.command()
def download(file_ref: str, output: Path, context: str):
    """Download to a new file and verify its checksum; never overwrite a user file."""
    limit = 25_000_000
    try:
        with httpx.stream("GET", base_url() + "/artifacts/" + file_ref,
                          headers=headers(context), timeout=120) as response:
            if response.status_code != 200:
                raise typer.BadParameter(f"Download failed: HTTP {response.status_code}")
            digest = hashlib.sha256()
            size = 0
            with output.open("xb") as dest:
                os.chmod(output, 0o600)
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ValueError("Transfer limit exceeded")
                    digest.update(chunk)
                    dest.write(chunk)
            if digest.hexdigest() != response.headers.get("X-Content-SHA256"):
                output.unlink()
                raise typer.BadParameter("Checksum mismatch")
    except FileExistsError:
        raise typer.BadParameter("Output exists; choose a new filename") from None
    typer.echo(str(output))
