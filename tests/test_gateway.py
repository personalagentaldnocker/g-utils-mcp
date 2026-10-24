import base64
from email import policy as email_policy
from email.message import EmailMessage
from email.parser import BytesParser

import pytest

from google_utils_mcp.artifacts import Artifacts
from google_utils_mcp.errors import AppError
from google_utils_mcp.gateway import Caller, Gateway
from google_utils_mcp.policy.constraints import constrain
from google_utils_mcp.policy.models import Grant
from google_utils_mcp.registry import REGISTRY, validate_params
from google_utils_mcp.services.gmail import compose, decode_raw, revision, summarize
from google_utils_mcp.storage import MemoryStore


class FakeNode:
    def __init__(self, root, path=()):
        self.root, self.path = root, path

    def __getattr__(self, name):
        def method(**kwargs):
            if kwargs:
                self.root.calls.append((self.path + (name,), kwargs))
                return self
            return FakeNode(self.root, self.path + (name,))

        return method

    def execute(self, **kwargs):
        return self.root.result

    def close(self):
        pass


class FakeClients:
    def __init__(self, result=None):
        self.calls = []
        self.accounts = []
        self.result = result or {"messages": [{"id": "one"}]}

    def build(self, policy, account, binding, api):
        self.accounts.append((account, api))
        return FakeNode(self)


def test_gateway_authorizes_before_loading_credentials(policy):
    clients = FakeClients()
    gateway = Gateway(clients, Artifacts(MemoryStore()))
    caller = Caller("agent", policy, 1)
    with pytest.raises(AppError):
        gateway.call(
            caller, "gmail_users_labels_delete", "test", "mail", {"userId": "me", "id": "Label_1"}
        )
    assert not clients.accounts
    result = gateway.call(
        caller, "gmail_users_messages_list", "test", "mail", {"userId": "me", "maxResults": 10}
    )
    assert result["messages"][0]["id"] == "one"
    assert clients.accounts == [("mail", "gmail")]
    with pytest.raises(AppError):
        gateway.call(caller, "gmail_users_messages_list", "test", "mail", {"userId": "other"})
    assert len(clients.accounts) == 1


@pytest.mark.parametrize(
    "params", [{"userId": "me", "maxResults": 101}, {"userId": "me", "access_token": "anything"}]
)
def test_discovery_validates_bounded_inputs(params):
    with pytest.raises(AppError):
        validate_params(REGISTRY["gmail_users_messages_list"], params)


def test_drive_and_docs_constraints():
    for method, params in [
        ("drive.files.update", {"body": {"trashed": True}}),
        ("docs.documents.batchUpdate", {"body": {"requests": [{"insertText": {"text": "a"}}]}}),
        ("gmail.users.threads.modify", {"body": {"addLabelIds": ["TRASH"]}}),
    ]:
        with pytest.raises(AppError):
            constrain(method, params, Grant())
    constrain(
        "docs.documents.batchUpdate",
        {
            "body": {
                "writeControl": {"requiredRevisionId": "r1"},
                "requests": [{"insertText": {"text": "x", "location": {"index": 1}}}],
            }
        },
        Grant(),
    )


def test_draft_preserves_thread_and_duplicate_attachments():
    msg = EmailMessage()
    msg["To"], msg["Subject"], msg["In-Reply-To"] = (
        "recipient@example.net",
        "Re: test",
        "<original>",
    )
    msg.set_content("old")
    msg.add_attachment(b"first", maintype="application", subtype="pdf", filename="same.pdf")
    msg.add_attachment(b"second", maintype="application", subtype="pdf", filename="same.pdf")
    raw = msg.as_bytes()
    draft = {
        "id": "draft",
        "message": {"raw": base64.urlsafe_b64encode(raw).decode(), "threadId": "thread"},
    }
    summary = summarize(draft)
    updated = compose(
        {
            "expected_revision": revision(raw),
            "text": "new",
            "remove_attachment_refs": [summary["attachments"][0]["attachment_ref"]],
        },
        draft,
        None,
        [],
    )
    parsed = BytesParser(policy=email_policy.default).parsebytes(
        decode_raw(updated["message"]["raw"])
    )
    assert updated["message"]["threadId"] == "thread"
    assert parsed["In-Reply-To"] == "<original>"
    assert [p.get_payload(decode=True) for p in parsed.iter_attachments()] == [b"second"]
    assert parsed.get_body(("plain",)).get_content().strip() == "new"
    with pytest.raises(AppError, match="changed"):
        compose({"expected_revision": "stale"}, draft, None, [])


def test_artifact_ownership_limit_expiry_and_integrity():
    store = MemoryStore()
    artifacts = Artifacts(store, limit=8)
    meta = artifacts.create("agent", "test", b"data", "../../evil\r\n.pdf")
    assert "/" not in meta["filename"] and "\r" not in meta["filename"]
    assert artifacts.get(meta["file_ref"], "agent", "test")[1] == b"data"
    with pytest.raises(AppError):
        artifacts.get(meta["file_ref"], "other", "test")
    with pytest.raises(AppError):
        artifacts.create("agent", "test", b"too large", "x")
    artifacts.ttl = -1
    expired = artifacts.create("agent", "test", b"x", "x")
    with pytest.raises(AppError):
        artifacts.get(expired["file_ref"], "agent", "test")
