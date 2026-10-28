import json

from starlette.testclient import TestClient

from g_utils.app import create_app
from g_utils.artifacts import Artifacts
from g_utils.config import Settings
from g_utils.policy.store import PolicyStore
from g_utils.storage import MemoryStore

from .conftest import TOKEN
from .test_gateway import FakeClients


def test_authenticated_http_mcp_and_artifact_transfer(policy_dict, secrets):
    store = MemoryStore()
    generation = store.put("policy", json.dumps(policy_dict).encode())
    app = create_app(
        Settings(),
        policies=PolicyStore(store, "policy"),
        secrets=secrets,
        artifacts=Artifacts(MemoryStore()),
        clients=FakeClients(),
    )
    headers = {"Authorization": "Bearer " + TOKEN, "Accept": "application/json, text/event-stream"}
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.post("/mcp").status_code == 401
        init = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert init.status_code == 200, init.text
        response = client.post(
            "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        names = [t["name"] for t in response.json()["result"]["tools"]]
        assert "gmail_users_messages_list" in names
        assert "gmail_users_labels_delete" not in names
        result = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "gmail_users_messages_list",
                    "arguments": {"context": "test", "account": "mail", "params": {"userId": "me"}},
                },
            },
        )
        assert result.json()["result"]["structuredContent"]["messages"][0]["id"] == "one", (
            result.text
        )
        upload_headers = {**headers, "X-Workspace-Context": "test", "X-Filename": "test.pdf"}
        uploaded = client.post("/artifacts", headers=upload_headers, content=b"file bytes")
        assert uploaded.status_code == 201
        ref = uploaded.json()["file_ref"]
        assert client.get("/artifacts/" + ref, headers=upload_headers).content == b"file bytes"
        policy_dict["principals"]["agent"]["enabled"] = False
        store.put("policy", json.dumps(policy_dict).encode(), generation)
        assert client.get("/artifacts/" + ref, headers=upload_headers).status_code == 401
