import base64
import hashlib
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses

from ..errors import AppError


def decode_raw(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def attachment_parts(message):
    return [
        (str(index), part)
        for index, part in enumerate(message.walk())
        if not part.is_multipart()
        and (part.get_filename() or part.get_content_disposition() == "attachment")
    ]


def summarize(draft: dict) -> dict:
    raw = decode_raw(draft["message"]["raw"])
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    rev = revision(raw)
    return {
        "id": draft["id"],
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


def compose(params: dict, existing: dict | None, reply: dict | None, files: list[tuple]) -> dict:
    if existing:
        raw = decode_raw(existing["message"]["raw"])
        rev = revision(raw)
        if params.get("expected_revision") != rev:
            raise AppError("conflict", "Draft changed; read again before editing", 409)
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        thread = existing["message"].get("threadId")
    else:
        msg = EmailMessage()
        thread = None
        if reply:
            original = BytesParser(policy=policy.default).parsebytes(decode_raw(reply["raw"]))
            thread = reply.get("threadId")
            msg["To"] = original.get("Reply-To", original.get("From", ""))
            subject = str(original.get("Subject", ""))
            msg["Subject"] = subject if subject.lower().startswith("re:") else "Re: " + subject
            if original.get("Message-ID"):
                msg["In-Reply-To"] = str(original["Message-ID"])
                msg["References"] = (
                    str(original.get("References", "")) + " " + str(original["Message-ID"])
                ).strip()
            if params.get("reply_all"):
                recipients = getaddresses(original.get_all("To", []) + original.get_all("Cc", []))
                own = params["own_email"].lower()
                cc = [address for _, address in recipients if address.lower() != own]
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
        if key in params:
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
            target = targets[ref]
            # Inline parts can be referenced by cid: in HTML. Keep the remaining MIME intact.
            for parent in msg.walk():
                if parent.is_multipart():
                    parent.set_payload([p for p in parent.get_payload() if p is not target])
    for meta, data in files:
        maintype, subtype = meta["mime_type"].split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=meta["filename"])
    payload = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    if thread:
        payload["threadId"] = thread
    return {"message": payload}
