from starlette.testclient import TestClient

from g_utils_mcp.app import create_app
from g_utils_mcp.mcp_server import Caller
from g_utils_mcp.utils.auth import authenticate

from .conftest import TOKEN

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"},
    },
}


def app_for(policy, secret):
    return create_app(lambda header: Caller(authenticate(header, policy, secret), policy, secret))


def test_health_needs_no_token(policy, secret):
    with TestClient(app_for(policy, secret)) as client:
        assert client.get("/healthz").status_code == 200


def test_mcp_requires_token(policy, secret):
    with TestClient(app_for(policy, secret)) as client:
        assert client.post("/mcp", json=INIT, headers=HEADERS).status_code == 401
        bad = {**HEADERS, "Authorization": "Bearer " + "x" * 43}
        assert client.post("/mcp", json=INIT, headers=bad).status_code == 401
        good = {**HEADERS, "Authorization": "Bearer " + TOKEN}
        response = client.post("/mcp", json=INIT, headers=good)
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["name"] == "g-utils-mcp"


def test_misconfiguration_is_unavailable_not_a_crash(monkeypatch):
    monkeypatch.delenv("POLICY_URI", raising=False)
    with TestClient(create_app()) as client:
        assert client.post("/mcp", json=INIT, headers=HEADERS).status_code == 503
