import base64
from email.message import EmailMessage

import pytest

from g_utils_mcp.mcp_server import call_tool, list_tools
from g_utils_mcp.utils.helpers import AppError

from .conftest import FakeClient

ARGS = {"context": "test", "account": "mail"}


def test_only_granted_tools_are_listed(who):
    names = {tool.name for tool in list_tools(who)}
    assert {"gmail_users_messages_list", "gmail_draft_compose", "drive_download"} <= names
    assert "gmail_users_labels_list" not in names
    assert "drive_upload" not in names


def test_generic_call_forces_own_mailbox(who):
    fake = FakeClient({"gmail.users.messages.list": {"messages": []}})
    result = call_tool(
        who, "gmail_users_messages_list", {**ARGS, "params": {"q": "x"}}, fake.factory
    )
    assert result == {"messages": []}
    assert fake.calls == [("gmail.users.messages.list", {"userId": "me", "q": "x"})]


def test_denied_and_invalid_calls_never_reach_google(who):
    fake = FakeClient({})
    with pytest.raises(AppError):
        call_tool(who, "gmail_users_labels_list", {**ARGS, "params": {}}, fake.factory)
    with pytest.raises(AppError):
        call_tool(who, "gmail_users_messages_list", {**ARGS, "params": {"bogus": 1}}, fake.factory)
    with pytest.raises(AppError):
        call_tool(
            who, "gmail_users_messages_list", {**ARGS, "account": "x", "params": {}}, fake.factory
        )
    assert fake.calls == []


def test_attachment_download_returns_base64(who):
    content = b"%PDF-1.4 test"
    encoded = base64.urlsafe_b64encode(content).decode()
    fake = FakeClient(
        {
            "gmail.users.messages.get": {
                "payload": {
                    "partId": "",
                    "parts": [
                        {
                            "partId": "1",
                            "filename": "a.pdf",
                            "mimeType": "application/pdf",
                            "body": {"attachmentId": "att", "size": len(content)},
                        }
                    ],
                }
            },
            "gmail.users.messages.attachments.get": {"data": encoded},
        }
    )
    result = call_tool(
        who,
        "gmail_attachment_download",
        {**ARGS, "params": {"message_id": "m", "part_id": "1"}},
        fake.factory,
    )
    assert base64.b64decode(result["data_base64"]) == content
    assert result["filename"] == "a.pdf" and result["size"] == len(content)


def test_reply_draft_with_attachment(who):
    original = EmailMessage()
    original["From"] = "sender@example.net"
    original["Subject"] = "Hello"
    original["Message-ID"] = "<1@example.net>"
    original.set_content("hi")
    raw = base64.urlsafe_b64encode(original.as_bytes()).decode()
    fake = FakeClient(
        {
            "gmail.users.messages.get": {"raw": raw, "threadId": "thread"},
            "gmail.users.drafts.create": lambda kwargs: {"id": "d1", "body": kwargs["body"]},
        }
    )
    file = {"filename": "n.txt", "mime_type": "text/plain", "data_base64": "aGk="}
    result = call_tool(
        who,
        "gmail_draft_compose",
        {**ARGS, "params": {"reply_to_message_id": "m", "text": "thanks", "add_files": [file]}},
        fake.factory,
    )
    message = result["body"]["message"]
    assert message["threadId"] == "thread"
    mime = base64.urlsafe_b64decode(message["raw"]).decode()
    assert "Re: Hello" in mime and "In-Reply-To: <1@example.net>" in mime and "n.txt" in mime


def test_drive_download_exports_google_docs(who):
    fake = FakeClient(
        {
            "drive.files.get": {
                "id": "f",
                "name": "Doc",
                "mimeType": "application/vnd.google-apps.document",
            },
            "drive.files.export_media": b"pdf-bytes",
        }
    )
    result = call_tool(who, "drive_download", {**ARGS, "params": {"file_id": "f"}}, fake.factory)
    assert base64.b64decode(result["data_base64"]) == b"pdf-bytes"
    assert result["mime_type"] == "application/pdf"


def test_capabilities_exclude_denied_methods(who):
    result = call_tool(who, "workspace_capabilities", {})
    assert "gmail.users.messages.list" in result["test"]["mail"]
    assert "gmail.users.messages.modify" not in result["test"]["mail"]
