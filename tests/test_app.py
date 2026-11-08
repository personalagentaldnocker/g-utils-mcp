import json
import os

import pytest
from starlette.testclient import TestClient

from g_utils_mcp import policy as pol
from g_utils_mcp.app import KNOWN, create_app

from .conftest import TOKEN, policy_blob

HEADERS = {"Authorization": "Bearer " + TOKEN, "Accept": "application/json, text/event-stream"}


def rpc(client, method, params=None, id=1):
    body = {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}
    return client.post("/mcp", headers=HEADERS, json=body)


def test_http_mcp_files_and_revocation(policy, google, files):
    blob = policy_blob(policy)
    with TestClient(create_app(pol.loader(blob, KNOWN))) as client:
        assert client.get("/healthz").status_code == 200
        assert client.post("/mcp").status_code == 401
        assert client.get("/oauth/google/callback").status_code == 401
        assert client.get("/oauth/google/callback", headers=HEADERS).status_code == 404
        init = rpc(
            client,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        assert init.status_code == 200, init.text
        names = [t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]]
        assert "gmail_users_messages_list" in names and "gmail_users_labels_delete" not in names
        call = {"name": "gmail_users_messages_list", "arguments": {"account": "mail", "params": {}}}
        result = rpc(client, "tools/call", call).json()["result"]
        assert result["structuredContent"]["messages"][0]["id"] == "one"
        denied = {
            "name": "gmail_users_labels_delete",
            "arguments": {"account": "mail", "params": {}},
        }
        assert rpc(client, "tools/call", denied).json()["result"]["isError"]

        uploaded = client.post("/files", headers={**HEADERS, "X-Filename": "a.pdf"}, content=b"pdf")
        assert uploaded.status_code == 201
        ref = uploaded.json()["file_ref"]
        downloaded = client.get("/files/" + ref, headers=HEADERS)
        assert downloaded.content == b"pdf" and downloaded.headers["x-content-sha256"]
        assert client.get("/files/" + "x" * 43, headers=HEADERS).status_code == 404

        policy["principals"]["agent"]["token_sha256"] = []
        blob.upload_from_string(json.dumps(policy).encode())
        assert client.get("/files/" + ref, headers=HEADERS).status_code == 401


@pytest.mark.live
def test_deployed_mcp_read_only_smoke():
    if os.environ.get("RUN_LIVE_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_TESTS=1, MCP_URL and MCP_TOKEN for deployed read-only smoke")
    import runpy

    runpy.run_path("scripts/smoke.py")["main"]()
