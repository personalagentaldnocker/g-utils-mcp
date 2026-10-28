import json
import os

import pytest

from g_utils.artifacts import Artifacts, Origin
from g_utils.errors import AppError
from g_utils.gateway import Caller, Gateway
from g_utils.registry import REGISTRY
from g_utils.storage import MemoryStore

from .test_gateway import FakeClients


@pytest.mark.parametrize("method", list(REGISTRY.values()), ids=list(REGISTRY))
def test_every_registered_wrapper_denies_before_credentials(policy, method):
    policy.contexts["test"].grants["agent"]["mail"].allow.clear()
    clients = FakeClients()
    gateway = Gateway(clients, Artifacts(MemoryStore()))
    with pytest.raises(AppError):
        gateway.call(Caller("agent", policy, 1), method.name, "test", "mail", {})
    assert not clients.accounts


@pytest.mark.parametrize("method", list(REGISTRY.values()), ids=list(REGISTRY))
def test_every_registered_api_binding_accepts_a_valid_request(policy, method):
    policy.contexts["test"].grants["agent"]["mail"].allow.append(method.id)
    params = {}
    for name in method.schema["required"]:
        params[name] = {} if name == "body" else "me" if name == "userId" else "Label_123"
    if method.id == "docs.documents.batchUpdate":
        params["body"] = {
            "requests": [{"insertText": {"text": "x", "location": {"index": 1}}}],
            "writeControl": {"requiredRevisionId": "revision"},
        }
    clients = FakeClients({"ok": True})
    result = Gateway(clients, Artifacts(MemoryStore())).run(
        Caller("agent", policy, 1), method.id, "test", "mail", params
    )
    assert result == {"ok": True}
    assert clients.calls[-1][0] == tuple(method.id.split(".")[1:])


def test_page_handle_is_bound_to_query_and_policy_generation(policy):
    clients = FakeClients({"messages": [], "nextPageToken": "google-private-page-token"})
    gateway = Gateway(clients, Artifacts(MemoryStore()))
    caller = Caller("agent", policy, 1)
    params = {"userId": "me", "q": "hello"}
    result = gateway.call(caller, "gmail_users_messages_list", "test", "mail", params)
    ref = result["nextPageToken"]
    assert ref != "google-private-page-token"
    gateway.call(caller, "gmail_users_messages_list", "test", "mail", {**params, "pageToken": ref})
    assert clients.calls[-1][1]["pageToken"] == "google-private-page-token"
    for altered, gen in [({**params, "q": "different"}, 1), (params, 2)]:
        with pytest.raises(AppError):
            gateway.call(
                Caller("agent", policy, gen),
                "gmail_users_messages_list",
                "test",
                "mail",
                {**altered, "pageToken": ref},
            )


def test_artifact_requires_export_grant_even_when_get_remains(policy):
    artifacts = Artifacts(MemoryStore())
    meta = artifacts.create(
        "agent",
        "test",
        b"data",
        "test.pdf",
        origin=Origin("mail", "drive.files.get", {"fileId": "file"}, ("drive.files.export",)),
    )
    policy.contexts["test"].grants["agent"]["mail"].allow.append("drive.files.get")
    clients = FakeClients()
    with pytest.raises(AppError):
        Gateway(clients, artifacts).artifact(Caller("agent", policy, 1), "test", meta["file_ref"])
    assert not clients.accounts


def test_audit_does_not_contain_message_content(policy, caplog):
    gateway = Gateway(FakeClients(), Artifacts(MemoryStore()))
    gateway.call(
        Caller("agent", policy, 1),
        "gmail_users_messages_list",
        "test",
        "mail",
        {"userId": "me", "q": "PRIVATE MESSAGE CONTENT"},
    )
    assert "PRIVATE MESSAGE CONTENT" not in caplog.text
    audit = json.loads(caplog.records[-1].message)
    assert audit["decision"] == "allowed" and audit["policy_generation"] == 1


def test_drive_download_resolves_shortcut_in_same_account(policy, monkeypatch):
    from g_utils.services import drive

    policy.contexts["test"].grants["agent"]["mail"].allow.append("drive.files.get")
    clients = FakeClients()
    gateway = Gateway(clients, Artifacts(MemoryStore()))
    reads = []

    def read(caller, method, context, account, params):
        reads.append((account, params["fileId"]))
        if params["fileId"] == "shortcut":
            return {
                "id": "shortcut",
                "name": "link",
                "mimeType": "application/vnd.google-apps.shortcut",
                "shortcutDetails": {"targetId": "actual"},
            }
        return {"id": "actual", "name": "test.pdf", "mimeType": "application/pdf"}

    monkeypatch.setattr(gateway, "run", read)
    monkeypatch.setattr(drive, "download", lambda req, limit: b"pdf bytes")
    result = gateway.call(
        Caller("agent", policy, 1), "drive_download", "test", "mail", {"file_id": "shortcut"}
    )
    assert reads == [("mail", "shortcut"), ("mail", "actual")]
    assert clients.calls[-1][1]["fileId"] == "actual"
    assert gateway.artifacts.get(result["file_ref"], "agent", "test")[1] == b"pdf bytes"


@pytest.mark.live
def test_deployed_mcp_read_only_smoke():
    if os.environ.get("RUN_LIVE_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_TESTS=1, MCP_URL and MCP_TOKEN for deployed read-only smoke")
    import runpy

    module = runpy.run_path("scripts/smoke.py")
    module["main"]()
