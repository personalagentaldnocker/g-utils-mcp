"""Gmail: the generic method list plus the hand-written draft and attachment tools.

`run(method_id, params)` is supplied by the MCP layer; it authorizes every call it makes.
"""

import base64
import hashlib
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses

from ..config import MAX_FILE_BYTES
from ..utils.helpers import AppError, User, file_in, file_out

METHODS = [
    "gmail.users.getProfile",
    "gmail.users.messages.list",
    "gmail.users.messages.get",
    "gmail.users.messages.modify",
    "gmail.users.messages.attachments.get",
    "gmail.users.threads.list",
    "gmail.users.threads.get",
    "gmail.users.threads.modify",
    "gmail.users.labels.list",
    "gmail.users.labels.get",
    "gmail.users.labels.create",
    "gmail.users.labels.update",
    "gmail.users.labels.patch",
    "gmail.users.labels.delete",
    "gmail.users.drafts.list",
    "gmail.users.drafts.get",
    "gmail.users.drafts.create",
    "gmail.users.drafts.update",
]


def decode_raw(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse(raw: bytes) -> EmailMessage:
    return BytesParser(policy=policy.default).parsebytes(raw)  # type: ignore[return-value]


def attachment_parts(message):
    return [
        (str(index), part)
        for index, part in enumerate(message.walk())
        if not part.is_multipart()
        and (part.get_filename() or part.get_content_disposition() == "attachment")
    ]


def summarize(draft: dict) -> dict:
    """Draft as headers, revision and attachment refs (refs are only valid for this revision)."""
    raw = decode_raw(draft["message"]["raw"])
    msg, rev = parse(raw), revision(raw)
    return {
        "id": draft["id"],
        "message_id": draft["message"].get("id"),
        "thread_id": draft["message"].get("threadId"),
        "revision": rev,
        "headers": {k: str(msg.get(k, "")) for k in ("To", "Cc", "Subject")},
        "attachments": [
            {
                "attachment_ref": rev + ":" + key,
                "filename": part.get_filename(),
                "mime_type": part.get_content_type(),
            }
            for key, part in attachment_parts(msg)
        ],
    }


def get_draft(run, draft_id: str) -> dict:
    return run("gmail.users.drafts.get", {"userId": "me", "id": draft_id, "format": "raw"})


def _start_reply(msg: EmailMessage, reply: dict, reply_all: bool, own_email: str) -> None:
    original = parse(decode_raw(reply["raw"]))
    msg["To"] = original.get("Reply-To", original.get("From", ""))
    subject = str(original.get("Subject", ""))
    msg["Subject"] = subject if subject.lower().startswith("re:") else "Re: " + subject
    if original.get("Message-ID"):
        msg["In-Reply-To"] = str(original["Message-ID"])
        references = str(original.get("References", "")) + " " + str(original["Message-ID"])
        msg["References"] = references.strip()
    if reply_all:
        recipients = getaddresses(original.get_all("To", []) + original.get_all("Cc", []))
        cc = [address for _, address in recipients if address.lower() != own_email.lower()]
        if cc:
            msg["Cc"] = ", ".join(cc)


def _set_body(msg: EmailMessage, text: str, subtype: str) -> None:
    body = next(
        (
            p
            for p in msg.walk()
            if not p.is_multipart()
            and p.get_content_type() == "text/" + subtype
            and not p.get_filename()
        ),
        None,
    )
    if body:
        body.set_content(text, subtype=subtype)
    elif not msg.is_multipart():
        if subtype == "plain" or not msg.get_payload():
            msg.set_content(text, subtype=subtype)
        else:
            msg.add_alternative(text, subtype=subtype)
    else:
        part = EmailMessage()
        part.set_content(text, subtype=subtype)
        msg.attach(part)


def compose(
    params: dict, existing: dict | None, reply: dict | None, own_email: str, files: list
) -> dict:
    """Build the Gmail draft body. Editing keeps every MIME part that is not changed."""
    rev = ""
    if existing:
        raw = decode_raw(existing["message"]["raw"])
        rev = revision(raw)
        if params.get("expected_revision") != rev:
            raise AppError("conflict", "Draft changed; read it again before editing", 409)
        msg, thread = parse(raw), existing["message"].get("threadId")
    else:
        msg, thread = EmailMessage(), None
        if reply:
            thread = reply.get("threadId")
            _start_reply(msg, reply, params.get("reply_all", False), own_email)
    for key, header in (("to", "To"), ("cc", "Cc"), ("subject", "Subject")):
        if key in params:
            value = ", ".join(params[key]) if isinstance(params[key], list) else params[key]
            if "\n" in value or "\r" in value:
                raise AppError("invalid_input", "Header contains a newline", 400)
            if header in msg:
                msg.replace_header(header, value)
            else:
                msg[header] = value
    if not existing and not msg.get("To"):
        raise AppError("invalid_input", "Draft needs a recipient", 400)
    for key, subtype in (("text", "plain"), ("html", "html")):
        if key in params:
            _set_body(msg, params[key], subtype)
    if params.get("remove_attachment_refs"):
        if not existing:
            raise AppError("invalid_input", "A new draft has no attachments to remove", 400)
        targets = {rev + ":" + key: part for key, part in attachment_parts(msg)}
        for ref in params["remove_attachment_refs"]:
            if ref not in targets:
                raise AppError("conflict", "Unknown attachment in this draft revision", 409)
            for parent in msg.walk():
                if parent.is_multipart():
                    parent.set_payload([p for p in parent.get_payload() if p is not targets[ref]])
    for data, name, mime_type in files:
        maintype, _, subtype = mime_type.partition("/")
        msg.add_attachment(
            data, maintype=maintype, subtype=subtype or "octet-stream", filename=name
        )
    raw = msg.as_bytes()
    if len(raw) > MAX_FILE_BYTES + 10_000_000:  # Gmail rejects drafts above about 35 MB
        raise AppError("too_large", "Draft exceeds Gmail's size limit", 413)
    payload = {"raw": base64.urlsafe_b64encode(raw).decode()}
    if thread:
        payload["threadId"] = thread
    return {"message": payload}


# --- Hand-written tools ---


def draft_compose(run, params: dict, user: User) -> dict:
    draft_id = params.get("draft_id")
    existing = get_draft(run, draft_id) if draft_id else None
    reply = None
    if params.get("reply_to_message_id"):
        reply = run(
            "gmail.users.messages.get",
            {"userId": "me", "id": params["reply_to_message_id"], "format": "raw"},
        )
    files = [file_in(user, spec) for spec in params.get("add_files", [])]
    body = compose(params, existing, reply, user.email, files)
    if not draft_id:
        return run("gmail.users.drafts.create", {"userId": "me", "body": body})
    # Re-read right before writing: Gmail has no atomic compare-and-set for drafts.
    if existing is None or get_draft(run, draft_id)["message"]["raw"] != existing["message"]["raw"]:
        raise AppError("conflict", "Draft changed during editing", 409)
    return run("gmail.users.drafts.update", {"userId": "me", "id": draft_id, "body": body})


def _find_part(part: dict, part_id: str) -> dict | None:
    if part.get("partId") == part_id:
        return part
    for child in part.get("parts", []):
        found = _find_part(child, part_id)
        if found:
            return found
    return None


def attachment_download(run, params: dict, user: User) -> dict:
    message_id = params["message_id"]
    message = run("gmail.users.messages.get", {"userId": "me", "id": message_id, "format": "full"})
    part = _find_part(message.get("payload", {}), params["part_id"])
    if part is None:
        raise AppError("not_found", "Message part not found", 404)
    body = part.get("body", {})
    if body.get("attachmentId"):
        if body.get("size", 0) > MAX_FILE_BYTES:
            raise AppError("too_large", "Attachment exceeds the size limit", 413)
        body = run(
            "gmail.users.messages.attachments.get",
            {"userId": "me", "messageId": message_id, "id": body["attachmentId"]},
        )
    raw = body.get("data", "")
    data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    if len(data) > MAX_FILE_BYTES:
        raise AppError("too_large", "Attachment exceeds the size limit", 413)
    name = part.get("filename") or "attachment"
    return file_out(user, data, name, part.get("mimeType", "application/octet-stream"))


# A file the agent sends: inline base64 (up to 5 MB) or a file_ref from POST /files.
FILE = {
    "type": "object",
    "properties": {
        "filename": {"type": "string"},
        "mime_type": {"type": "string"},
        "data_base64": {"type": "string"},
        "file_ref": {"type": "string"},
    },
    "additionalProperties": False,
}

# name: (description, params schema, required params, methods that make it visible, function)
TOOLS = {
    "gmail_draft_compose": (
        "Create or edit an unsent draft; editing keeps other MIME parts. Read the draft "
        "(gmail_users_drafts_get) first and pass its revision as expected_revision.",
        {
            "draft_id": {"type": "string"},
            "expected_revision": {"type": "string"},
            "to": {"type": "array", "items": {"type": "string"}},
            "cc": {"type": "array", "items": {"type": "string"}},
            "subject": {"type": "string"},
            "text": {"type": "string"},
            "html": {"type": "string"},
            "reply_to_message_id": {"type": "string"},
            "reply_all": {"type": "boolean"},
            "add_files": {"type": "array", "maxItems": 10, "items": FILE},
            "remove_attachment_refs": {
                "type": "array",
                "maxItems": 100,
                "items": {"type": "string"},
            },
        },
        [],
        ["gmail.users.drafts.create", "gmail.users.drafts.update"],
        draft_compose,
    ),
    "gmail_attachment_download": (
        "Return one MIME part (inline or attached file) of a message: base64 up to 5 MB, "
        "otherwise a file_ref to download from GET /files/<ref>.",
        {"message_id": {"type": "string"}, "part_id": {"type": "string"}},
        ["message_id", "part_id"],
        ["gmail.users.messages.get"],
        attachment_download,
    ),
}
