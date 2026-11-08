import base64

import pytest
from starlette.testclient import TestClient

from g_utils_mcp import config
from g_utils_mcp.app import create_app
from g_utils_mcp.mcp_server import Caller, call_tool
from g_utils_mcp.utils.auth import authenticate
from g_utils_mcp.utils.helpers import AppError, User, file_in, file_load, file_out, file_store

from .conftest import TOKEN, FakeClient

ARGS = {"context": "test", "account": "mail"}
USER = User("agent", "me@example.net")


def test_small_files_inline_large_files_by_ref(bucket):
    small = file_out(USER, b"x" * 10, "s.txt", "text/plain")
    assert base64.b64decode(small["data_base64"]) == b"x" * 10 and not bucket.store
    big = b"y" * (config.INLINE_FILE_BYTES + 1)
    result = file_out(USER, big, "b.bin", "application/octet-stream")
    assert "data_base64" not in result
    assert file_load("agent", result["file_ref"]) == (big, "b.bin", "application/octet-stream")


def test_file_refs_belong_to_one_agent_and_expire(bucket, monkeypatch):
    ref = file_store("agent", b"data", "a.txt", "text/plain")
    with pytest.raises(AppError):
        file_load("someone-else", ref)
    with pytest.raises(AppError):
        file_load("agent", "../" + ref)
    monkeypatch.setattr(config, "FILE_REF_SECONDS", -1)
    with pytest.raises(AppError):
        file_load("agent", ref)


def test_file_in_accepts_inline_or_ref(bucket):
    ref = file_store("agent", b"from-bucket", "r.pdf", "application/pdf")
    assert file_in(USER, {"file_ref": ref}) == (b"from-bucket", "r.pdf", "application/pdf")
    assert file_in(USER, {"data_base64": "aGk=", "filename": "h.txt"})[:2] == (b"hi", "h.txt")
    with pytest.raises(AppError):
        file_in(USER, {})


def test_large_drive_download_goes_through_bucket(who, bucket):
    big = b"z" * (config.INLINE_FILE_BYTES + 1)
    fake = FakeClient(
        {
            "drive.files.get": {"id": "f", "name": "big.bin", "mimeType": "application/zip"},
            "drive.files.get_media": big,
        }
    )
    result = call_tool(who, "drive_download", {**ARGS, "params": {"file_id": "f"}}, fake.factory)
    assert file_load("agent", result["file_ref"])[0] == big


def test_upload_and_download_endpoints(policy, secret, bucket):
    app = create_app(lambda header: Caller(authenticate(header, policy, secret), policy, secret))
    auth = {"Authorization": "Bearer " + TOKEN}
    with TestClient(app) as client:
        assert client.post("/files", content=b"abc").status_code == 401
        response = client.post(
            "/files",
            content=b"abc",
            headers={**auth, "X-Filename": "a.txt", "Content-Type": "text/plain"},
        )
        assert response.status_code == 201
        ref = response.json()["file_ref"]
        assert client.get("/files/" + ref).status_code == 401
        download = client.get("/files/" + ref, headers=auth)
        assert download.content == b"abc"
        assert download.headers["x-content-sha256"] == response.json()["sha256"]
        assert client.get("/files/" + "x" * 43, headers=auth).status_code == 404
