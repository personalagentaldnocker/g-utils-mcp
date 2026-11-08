"""Gmail tools. Everything not listed here goes through the generic dispatcher in app.py.

Sending mail and deleting messages are intentionally not implemented.
"""

import base64
import hashlib
from email import policy as email_policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses

from . import policy, utils
from .policy import Caller
from .utils import AppError

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


def decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse(raw: bytes) -> EmailMessage:
    return BytesParser(policy=email_policy.default).parsebytes(raw)  # type: ignore[return-value]


def attachment_parts(msg: EmailMessage) -> list[tuple[str, EmailMessage]]:
    return [
        (str(index), part)
        for index, part in enumerate(msg.walk())
        if not part.is_multipart()
        and (part.get_filename() or part.get_content_disposition() == "attachment")
    ]


def summarize(draft: dict) -> dict:
    raw = decode(draft["message"]["raw"])
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


def _get_draft(caller: Caller, account: str, draft_id: str) -> dict:
    return policy.run(caller, account, "gmail.users.drafts.get", {"id": draft_id, "format": "raw"})


# --- Overrides of generic methods --------------------------------------------------------------


def drafts_get(caller: Caller, account: str, params: dict, extra: dict) -> dict:
    """Return headers, attachment refs and a revision instead of the raw MIME."""
    return summarize(_get_draft(caller, account, params["id"]))


def drafts_update(caller: Caller, account: str, params: dict, extra: dict) -> dict:
    policy.check(caller, account, "gmail_users_drafts_update")
    current = _get_draft(caller, account, params["id"])
    if revision(decode(current["message"]["raw"])) != extra.get("expected_revision"):
        raise AppError("conflict", "An unchanged draft revision is required", 409)
    return policy.run(caller, account, "gmail.users.drafts.update", params)


def attachments_get(caller: Caller, account: str, params: dict, extra: dict) -> dict:
    """Store the attachment bytes in the temporary bucket instead of the tool result."""
    tool = "gmail_users_messages_attachments_get"
    result = policy.run(caller, account, "gmail.users.messages.attachments.get", params)
    data = decode(result["data"])
    name = extra.get("filename", "attachment")
    return utils.put_file(
        caller.principal, account, data, name, "application/octet-stream", tool, (tool,)
    )


OVERRIDES = {
    "gmail.users.drafts.get": drafts_get,
    "gmail.users.drafts.update": drafts_update,
    "gmail.users.messages.attachments.get": attachments_get,
}


# --- Helper tools ------------------------------------------------------------------------------


def attachment_download(caller: Caller, account: str, params: dict) -> dict:
    """Store one MIME part (inline or external attachment) of a message as a temporary file."""
    tool = "gmail_attachment_download"
    policy.check(caller, account, tool)
    message = policy.run(
        caller, account, "gmail.users.messages.get", {"id": params["message_id"], "format": "full"}
    )

    def find(part: dict) -> dict | None:
        if part.get("partId") == params["part_id"]:
            return part
        return next((f for c in part.get("parts", []) if (f := find(c))), None)

    part = find(message.get("payload", {}))
    if part is None:
        raise AppError("not_found", "Message part not found", 404)
    body = part.get("body", {})
    requires: tuple[str, ...] = (tool, "gmail_users_messages_get")
    if body.get("attachmentId"):
        args = {"messageId": params["message_id"], "id": body["attachmentId"]}
        body = policy.run(caller, account, "gmail.users.messages.attachments.get", args)
        requires += ("gmail_users_messages_attachments_get",)
    return utils.put_file(
        caller.principal,
        account,
        decode(body.get("data", "")),
        part.get("filename") or "attachment",
        part.get("mimeType", "application/octet-stream"),
        tool,
        requires,
    )


def draft_compose(caller: Caller, account: str, params: dict) -> dict:
    """Create or edit an unsent draft, keeping other MIME parts. Never sends."""
    tool = "gmail_draft_compose"
    policy.check(caller, account, tool)
    draft_id = params.get("draft_id")
    method = "gmail.users.drafts.update" if draft_id else "gmail.users.drafts.create"
    policy.check(caller, account, policy.tool_name(method))
    existing = _get_draft(caller, account, draft_id) if draft_id else None
    reply = None
    if params.get("reply_to_message_id"):
        args = {"id": params["reply_to_message_id"], "format": "raw"}
        reply = policy.run(caller, account, "gmail.users.messages.get", args)
    files = [policy.get_file(caller, ref, tool) for ref in params.get("add_file_refs", [])]
    own = caller.policy["accounts"][account]["email"]
    body = compose(params, own, existing, reply, files)
    if len(body["message"]["raw"]) > 30_000_000:
        raise AppError("too_large", "Composed message exceeds size limit", 413)
    args = {"body": body}
    if draft_id:
        # Re-read just before writing; Gmail has no atomic compare-and-set for drafts.
        latest = _get_draft(caller, account, draft_id)
        if existing is None or latest["message"]["raw"] != existing["message"]["raw"]:
            raise AppError("conflict", "Draft changed during editing", 409)
        args["id"] = draft_id
    return policy.run(caller, account, method, args)


def compose(
    params: dict, own_email: str, existing: dict | None, reply: dict | None, files: list[tuple]
) -> dict:
    if existing:
        raw = decode(existing["message"]["raw"])
        rev = revision(raw)
        if params.get("expected_revision") != rev:
            raise AppError("conflict", "Draft changed; read again before editing", 409)
        msg = parse(raw)
        thread = existing["message"].get("threadId")
    else:
        msg, thread = EmailMessage(), None
        if reply:
            original = parse(decode(reply["raw"]))
            thread = reply.get("threadId")
            msg["To"] = original.get("Reply-To", original.get("From", ""))
            subject = str(original.get("Subject", ""))
            msg["Subject"] = subject if subject.lower().startswith("re:") else "Re: " + subject
            if original.get("Message-ID"):
                msg["In-Reply-To"] = str(original["Message-ID"])
                refs = str(original.get("References", "")) + " " + str(original["Message-ID"])
                msg["References"] = refs.strip()
            if params.get("reply_all"):
                recipients = getaddresses(original.get_all("To", []) + original.get_all("Cc", []))
                cc = [a for _, a in recipients if a.lower() != own_email.lower()]
                if cc:
                    msg["Cc"] = ", ".join(cc)
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
        if key not in params:
            continue
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
            body.set_content(params[key], subtype=subtype)
        elif not msg.is_multipart() and not msg.get_content_type().startswith("multipart/"):
            if key == "text" or not msg.get_payload():
                msg.set_content(params[key], subtype=subtype)
            else:
                msg.add_alternative(params[key], subtype=subtype)
        else:
            part = EmailMessage()
            part.set_content(params[key], subtype=subtype)
            msg.attach(part)
    if params.get("remove_attachment_refs"):
        if not existing:
            raise AppError("invalid_input", "Cannot remove attachments from a new draft", 400)
        targets = {rev + ":" + key: part for key, part in attachment_parts(msg)}
        for ref in params["remove_attachment_refs"]:
            if ref not in targets:
                raise AppError("conflict", "Unknown attachment in this draft revision", 409)
            # Inline parts may be referenced by cid: in HTML; keep the rest of the MIME tree.
            for parent in msg.walk():
                if parent.is_multipart():
                    parent.set_payload([p for p in parent.get_payload() if p is not targets[ref]])
    for meta, data in files:
        maintype, subtype = meta["mime_type"].split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=meta["filename"])
    payload = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    if thread:
        payload["threadId"] = thread
    return {"message": payload}


COMPOSE_PARAMS = {
    "draft_id": {"type": "string"},
    "expected_revision": {"type": "string"},
    "to": {"type": "array", "items": {"type": "string"}},
    "cc": {"type": "array", "items": {"type": "string"}},
    "subject": {"type": "string"},
    "text": {"type": "string"},
    "html": {"type": "string"},
    "reply_to_message_id": {"type": "string"},
    "reply_all": {"type": "boolean"},
    "add_file_refs": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
    "remove_attachment_refs": {"type": "array", "maxItems": 100, "items": {"type": "string"}},
}

# name -> (description, params properties, required params, function)
HELPERS = {
    "gmail_attachment_download": (
        "Save one MIME part (inline or attachment) of a message as a temporary file_ref.",
        {"message_id": {"type": "string"}, "part_id": {"type": "string"}},
        ["message_id", "part_id"],
        attachment_download,
    ),
    "gmail_draft_compose": (
        "Create or edit an unsent draft, keeping other MIME parts. To edit, pass draft_id and "
        "the expected_revision from gmail_users_drafts_get. Never sends mail.",
        COMPOSE_PARAMS,
        [],
        draft_compose,
    ),
}
