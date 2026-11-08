"""The `g-utils-mcp` command: run the server, and move files to and from it.

`upload` and `download` let an MCP client hand file bytes to the server (and get them
back) without the bytes passing through the model. Administration lives in scripts/admin.py.
"""

import hashlib
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import quote

import httpx
import typer

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
LIMIT = 25_000_000


@app.command()
def serve(host: str = "0.0.0.0", port: int = 0):
    """Run the MCP server (Cloud Run entry point)."""
    import uvicorn

    from .app import create_app

    port = port or int(os.environ.get("PORT", 8080))
    uvicorn.run(create_app(), host=host, port=port, access_log=False)


def _headers() -> dict:
    token = os.environ.get("MCP_TOKEN")
    if not token:
        raise typer.BadParameter("Set MCP_TOKEN in the environment")
    return {"Authorization": "Bearer " + token}


def _url(path: str) -> str:
    url = os.environ.get("MCP_URL", "").rstrip("/")
    if not url.startswith("https://"):
        raise typer.BadParameter("Set MCP_URL to the HTTPS service origin")
    return url + path


@app.command()
def upload(file: Path):
    """Upload a local file; prints the file_ref to pass to drive_upload or gmail_draft_compose."""
    if file.stat().st_size > LIMIT:
        raise typer.BadParameter("File exceeds the transfer limit")
    headers = {
        **_headers(),
        "X-Filename": quote(file.name),
        "Content-Type": mimetypes.guess_type(file.name)[0] or "application/octet-stream",
    }
    with file.open("rb") as source, httpx.Client(timeout=120) as client:
        response = client.post(_url("/files"), headers=headers, content=source)
    if response.status_code != 201:
        raise typer.BadParameter(f"Upload failed: HTTP {response.status_code}")
    typer.echo(json.dumps(response.json()))


@app.command()
def download(file_ref: str, output: Path):
    """Download a file_ref to a new local file (never overwrites) and verify its sha256."""
    try:
        fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise typer.BadParameter("Output exists; choose a new filename") from None
    try:
        digest, size = hashlib.sha256(), 0
        with (
            os.fdopen(fd, "wb") as dest,
            httpx.stream("GET", _url("/files/" + file_ref), headers=_headers(), timeout=120) as r,
        ):
            if r.status_code != 200:
                raise typer.BadParameter(f"Download failed: HTTP {r.status_code}")
            for chunk in r.iter_bytes():
                size += len(chunk)
                if size > LIMIT:
                    raise typer.BadParameter("Transfer limit exceeded")
                digest.update(chunk)
                dest.write(chunk)
        if digest.hexdigest() != r.headers.get("X-Content-SHA256"):
            raise typer.BadParameter("Checksum mismatch")
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    typer.echo(str(output))
