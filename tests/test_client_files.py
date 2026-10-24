import hashlib

import httpx
from typer.testing import CliRunner

from google_utils_mcp import cli


def test_file_client_checksum_and_preserves_existing_output(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_TOKEN", "test")
    monkeypatch.setenv("MCP_URL", "https://service.example.net")
    original = httpx.stream

    def handler(request):
        return httpx.Response(
            200, content=b"file", headers={"X-Content-SHA256": hashlib.sha256(b"file").hexdigest()}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: client.stream(*args, **kwargs))
    output = tmp_path / "download.pdf"
    runner = CliRunner()
    args = ["download", "reference", str(output), "--context", "private"]
    assert runner.invoke(cli.app, args).exit_code == 0
    assert output.read_bytes() == b"file"
    assert runner.invoke(cli.app, args).exit_code != 0
    assert output.read_bytes() == b"file"
    monkeypatch.setattr(httpx, "stream", original)


def test_file_client_cleans_up_bad_checksum(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_TOKEN", "test")
    monkeypatch.setenv("MCP_URL", "https://service.example.net")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=b"bad", headers={"X-Content-SHA256": "wrong"})
        )
    )
    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: client.stream(*args, **kwargs))
    output = tmp_path / "download.pdf"
    assert (
        CliRunner()
        .invoke(cli.app, ["download", "ref", str(output), "--context", "private"])
        .exit_code
        != 0
    )
    assert not output.exists()
