import base64
import json
from email.message import EmailMessage

import pytest

from g_utils_mcp import app, gmail, policy, utils
from g_utils_mcp.utils import AppError

from .conftest import allow

GENERIC = sorted(set(app.METHODS) - {policy.tool_name(m) for m in app.OVERRIDES})


def valid_params(method: str) -> dict:
    schema = utils.method_schema(method)
    params = {
        name: {} if name == "body" else "me" if name == "userId" else "Label_1"
        for name in schema["required"]
    }
    if method == "docs.documents.batchUpdate":
        params["body"] = {
            "requests": [{"insertText": {"text": "x", "location": {"index": 1}}}],
            "writeControl": {"requiredRevisionId": "r"},
        }
    return params


@pytest.mark.parametrize("name", sorted(set(app.METHODS) | set(app.HELPERS)))
def test_every_tool_denies_before_loading_credentials(caller, google, files, name):
    caller.policy["grants"]["agent"]["mail"]["allow"].clear()
    with pytest.raises(AppError):
        app.call_tool(caller, name, {"account": "mail", "params": {}})
    assert google.credential_loads == [] and google.calls == []


@pytest.mark.parametrize("name", GENERIC)
def test_every_generic_tool_reaches_its_google_method(caller, google, name):
    allow(caller, name)
    method = app.METHODS[name]
    google.result = {"ok": True}
    assert app.call_tool(caller, name, {"account": "mail", "params": valid_params(method)}) == {
        "ok": True
    }
    assert google.calls[-1][0] == tuple(method.split("."))


def test_gmail_user_must_be_me(caller, google):
    with pytest.raises(AppError):
        app.call_tool(
            caller, "gmail_users_messages_list", {"account": "mail", "params": {"userId": "x"}}
        )
    app.call_tool(caller, "gmail_users_messages_list", {"account": "mail", "params": {}})
    assert google.calls[-1][1]["userId"] == "me"


def test_page_tokens_pass_through(caller, google):
    google.result = {"messages": [], "nextPageToken": "google-token"}
    args = {"account": "mail", "params": {"q": "x"}}
    assert (
        app.call_tool(caller, "gmail_users_messages_list", args)["nextPageToken"] == "google-token"
    )
    args["params"]["pageToken"] = "google-token"
    app.call_tool(caller, "gmail_users_messages_list", args)
    assert google.calls[-1][1]["pageToken"] == "google-token"


def test_log_has_no_arguments(caller, google, caplog):
    args = {"account": "mail", "params": {"q": "PRIVATE CONTENT"}}
    app.logged_call(caller, "gmail_users_messages_list", args)
    assert "PRIVATE CONTENT" not in caplog.text
    entry = json.loads(caplog.records[-1].message)
    assert entry["tool"] == "gmail_users_messages_list" and entry["error"] == ""


def test_capabilities_show_only_own_effective_tools(caller):
    caller.policy["grants"]["other"] = {"mail": {"allow": ["drive_files_get"]}}
    assert app.call_tool(caller, "workspace_capabilities", {}) == {
        "mail": ["docs_documents_get", "drive_files_list", "gmail_users_messages_list"]
    }
    names = {t.name for t in app.list_tools(caller)}
    assert "drive_files_get" not in names and "gmail_users_messages_list" in names


def raw_draft(*attachments: bytes) -> tuple[bytes, dict]:
    msg = EmailMessage()
    msg["To"], msg["Subject"], msg["In-Reply-To"] = "r@example.net", "Re: test", "<original>"
    msg.set_content("old")
    for data in attachments:
        msg.add_attachment(data, maintype="application", subtype="pdf", filename="same.pdf")
    raw = msg.as_bytes()
    return raw, {
        "id": "draft",
        "message": {"raw": base64.urlsafe_b64encode(raw).decode(), "threadId": "thread"},
    }


def test_compose_keeps_thread_and_removes_one_of_two_same_named_attachments():
    raw, draft = raw_draft(b"first", b"second")
    summary = gmail.summarize(draft)
    params = {
        "expected_revision": gmail.revision(raw),
        "text": "new",
        "remove_attachment_refs": [summary["attachments"][0]["attachment_ref"]],
    }
    updated = gmail.compose(params, "me@example.net", draft, None, [])
    parsed = gmail.parse(gmail.decode(updated["message"]["raw"]))
    assert updated["message"]["threadId"] == "thread"
    assert parsed["In-Reply-To"] == "<original>"
    assert [p.get_payload(decode=True) for p in parsed.iter_attachments()] == [b"second"]
    assert parsed.get_body(("plain",)).get_content().strip() == "new"
    with pytest.raises(AppError, match="changed"):
        gmail.compose({"expected_revision": "stale"}, "me@example.net", draft, None, [])


def test_draft_compose_needs_helper_and_underlying_grants(caller, google):
    raw, draft = raw_draft()
    google.results["get"] = draft
    google.results["update"] = {"id": "draft"}
    args = {"account": "mail", "params": {"draft_id": "draft", "text": "x"}}
    args["params"]["expected_revision"] = gmail.revision(raw)
    allow(caller, "gmail_draft_compose", "gmail_users_drafts_update")
    with pytest.raises(AppError):  # gmail_users_drafts_get is not granted
        app.call_tool(caller, "gmail_draft_compose", args)
    allow(caller, "gmail_users_drafts_get")
    assert app.call_tool(caller, "gmail_draft_compose", args) == {"id": "draft"}
    caller.policy["grants"]["agent"]["mail"]["deny"].append("gmail_users_drafts_update")
    with pytest.raises(AppError):
        app.call_tool(caller, "gmail_draft_compose", args)


def test_drafts_update_requires_unchanged_revision(caller, google):
    _, draft = raw_draft()
    google.results["get"] = draft
    allow(caller, "gmail_users_drafts_get", "gmail_users_drafts_update")
    args = {"account": "mail", "params": {"id": "draft", "body": {}}, "expected_revision": "old"}
    with pytest.raises(AppError, match="revision"):
        app.call_tool(caller, "gmail_users_drafts_update", args)


def test_files_are_private_expire_and_recheck_source_grants(caller, files):
    meta = utils.put_file(
        "agent",
        "mail",
        b"data",
        "../../evil\r\n.pdf",
        "application/pdf",
        "t",
        ("drive_files_list",),
    )
    assert "/" not in meta["filename"] and "\r" not in meta["filename"]
    assert policy.get_file(caller, meta["file_ref"], "t")[1] == b"data"
    with pytest.raises(AppError):
        utils.get_file("other", meta["file_ref"], "t")
    caller.policy["grants"]["agent"]["mail"]["deny"].append("drive_files_list")
    with pytest.raises(AppError):
        policy.get_file(caller, meta["file_ref"], "t")
    stored = json.loads(files.objects["files/" + meta["file_ref"]].metadata["meta"])
    stored["expires"] = 0
    files.objects["files/" + meta["file_ref"]].metadata = {"meta": json.dumps(stored)}
    with pytest.raises(AppError):
        utils.get_file("agent", meta["file_ref"], "t")
    with pytest.raises(AppError):
        utils.put_file("agent", "mail", b"x" * (utils.TRANSFER_LIMIT + 1), "x", "a/b", "t")


def test_file_transfers_are_logged_with_size(files, caplog):
    meta = utils.put_file("agent", "mail", b"SECRET BYTES", "f.txt", "text/plain", "t")
    utils.get_file("agent", meta["file_ref"], "t")
    events = [json.loads(r.message) for r in caplog.records]
    assert [e["event"] for e in events] == ["file_put", "file_get"]
    assert all(e["size"] == 12 and e["sha256"] == meta["sha256"] for e in events)
    assert "SECRET BYTES" not in caplog.text and "f.txt" not in caplog.text


def test_drive_download_follows_shortcuts_and_needs_export_grant(caller, google, files):
    metas = {
        "shortcut": {
            "id": "shortcut",
            "name": "link",
            "mimeType": "application/vnd.google-apps.shortcut",
            "shortcutDetails": {"targetId": "doc"},
        },
        "doc": {"id": "doc", "name": "Doc", "mimeType": "application/vnd.google-apps.document"},
    }
    google.results["get"] = lambda kwargs: metas[kwargs["fileId"]]
    google.downloads["export_media"] = b"pdf bytes"
    allow(caller, "drive_download", "drive_files_get")
    args = {"account": "mail", "params": {"file_id": "shortcut"}}
    with pytest.raises(AppError):
        app.call_tool(caller, "drive_download", args)
    allow(caller, "drive_files_export")
    result = app.call_tool(caller, "drive_download", args)
    assert google.calls[-1] == (
        ("drive", "files", "export_media"),
        {"fileId": "doc", "mimeType": "application/pdf"},
    )
    assert policy.get_file(caller, result["file_ref"], "t")[1] == b"pdf bytes"
