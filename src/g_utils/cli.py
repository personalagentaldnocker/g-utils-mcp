import hashlib
import json
import os
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import httpx
import typer

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)


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
def upload(file: Path, context: Annotated[str, typer.Option()]):
    """Upload binary bytes without placing them in the model context."""
    import mimetypes

    hdr = headers(context)
    if file.stat().st_size > 20_000_000:
        raise typer.BadParameter("File exceeds the default 20 MB transfer limit")
    hdr["X-Filename"] = quote(file.name)
    hdr["Content-Type"] = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    with file.open("rb") as source, httpx.Client(timeout=120) as client:
        response = client.post(base_url() + "/artifacts", headers=hdr, content=source)
    if response.status_code != 201:
        raise typer.BadParameter(f"Upload failed: HTTP {response.status_code}")
    typer.echo(json.dumps(response.json()))


@app.command()
def download(file_ref: str, output: Path, context: Annotated[str, typer.Option()]):
    """Download to a new file and verify its checksum; never overwrite a user file."""
    limit = 25_000_000
    created = False
    try:
        with httpx.stream(
            "GET", base_url() + "/artifacts/" + file_ref, headers=headers(context), timeout=120
        ) as response:
            if response.status_code != 200:
                raise typer.BadParameter(f"Download failed: HTTP {response.status_code}")
            digest = hashlib.sha256()
            size = 0
            fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            created = True
            with os.fdopen(fd, "wb") as dest:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ValueError("Transfer limit exceeded")
                    digest.update(chunk)
                    dest.write(chunk)
            if digest.hexdigest() != response.headers.get("X-Content-SHA256"):
                raise typer.BadParameter("Checksum mismatch")
    except FileExistsError:
        raise typer.BadParameter("Output exists; choose a new filename") from None
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise
    typer.echo(str(output))
