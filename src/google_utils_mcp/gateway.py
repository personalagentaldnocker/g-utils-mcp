import base64
import io
import json
import secrets
import time
from dataclasses import dataclass

from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from .artifacts import Artifacts, Origin
from .audit import event
from .errors import AppError, forbidden
from .policy.authorize import authorize
from .policy.constraints import constrain
from .policy.models import Policy
from .registry import REGISTRY, validate_params
from .services import drive, gmail


@dataclass(frozen=True)
class Caller:
    principal: str
    policy: Policy
    generation: int


class Gateway:
    def __init__(self, clients, artifacts: Artifacts, result_limit: int = 1_000_000):
        self.clients, self.artifacts, self.result_limit = clients, artifacts, result_limit

    def run(
        self, caller: Caller, method_id: str, context: str, account: str, params: dict, media=None
    ):
        method = REGISTRY.get(method_id.replace(".", "_"))
        grant, binding = authorize(caller.policy, caller.principal, context, account, method_id)
        if method:
            validate_params(method, params)
        elif method_id != "drive.files.export":
            raise forbidden()
        constrain(method_id, params, grant)
        # The path comes from the code-owned registry, never from tool arguments.
        api = method_id.split(".")[0]
        service = self.clients.build(caller.policy, account, binding, api)
        try:
            resource = service
            parts = method_id.split(".")[1:]
            for part in parts[:-1]:
                resource = getattr(resource, part)()
            args = dict(params)
            if args.get("pageToken"):
                ref = args["pageToken"]
                if not isinstance(ref, str) or not __import__("re").fullmatch(
                    r"[A-Za-z0-9_-]{43}", ref
                ):
                    raise forbidden()
                page = json.loads(self.artifacts.store.read("pages/" + ref).data)
                query = {k: v for k, v in params.items() if k != "pageToken"}
                if (
                    page["principal"] != caller.principal
                    or page["account"] != account
                    or page["context"] != context
                    or page["method"] != method_id
                    or page["generation"] != caller.generation
                    or page["query"] != query
                    or page["expires"] <= time.time()
                ):
                    raise forbidden()
                args["pageToken"] = page["token"]
            if api == "gmail":
                args["userId"] = "me"
            if media is not None:
                args["media_body"] = media
            result = getattr(resource, parts[-1])(**args).execute(num_retries=0)
            if result in (None, ""):
                result = {"success": True}
            if isinstance(result, dict) and result.get("nextPageToken"):
                ref = secrets.token_urlsafe(32)
                page = {
                    "principal": caller.principal,
                    "account": account,
                    "context": context,
                    "method": method_id,
                    "generation": caller.generation,
                    "query": {k: v for k, v in params.items() if k != "pageToken"},
                    "token": result["nextPageToken"],
                    "expires": time.time() + 1800,
                }
                self.artifacts.store.put("pages/" + ref, json.dumps(page).encode())
                result = {**result, "nextPageToken": ref}
            return result
        except HttpError as exc:
            status = int(exc.resp.status)
            if status == 429:
                raise AppError("rate_limited", "Google quota exceeded; retry later", 429) from None
            if status in (401, 403, 404):
                raise AppError(
                    "upstream_denied", "Google denied the requested operation", status
                ) from None
            if status == 400:
                raise AppError(
                    "invalid_input", "Google rejected the request; check arguments or revision", 400
                ) from None
            if status in (409, 412):
                raise AppError("conflict", "Resource revision changed; read again", 409) from None
            if status >= 500 and method_id.rsplit(".", 1)[-1] not in (
                "get",
                "list",
                "getProfile",
                "export",
            ):
                raise AppError(
                    "uncertain_write",
                    "Google write outcome is uncertain; reconcile before retrying",
                    502,
                ) from None
            raise AppError("upstream_failure", "Google operation failed", 502) from None
        except (TimeoutError, OSError):
            write = method_id.rsplit(".", 1)[-1] not in ("get", "list", "getProfile", "export")
            raise AppError(
                "uncertain_write" if write else "upstream_failure",
                "Request failed; reconcile writes before retrying",
                502,
            ) from None
        except GoogleAuthError:
            raise AppError("reauth_required", "Reconnect the Google account", 401) from None
        finally:
            service.close()

    def artifact(self, caller: Caller, context: str, ref: str) -> tuple[dict, bytes]:
        meta, data = self.artifacts.get(ref, caller.principal, context)
        if meta["origin"]:
            origin = meta["origin"]
            for method in origin.get("required_methods", []):
                authorize(caller.policy, caller.principal, context, origin["account"], method)
            # Re-authorize and make a minimal source read under the current caller policy.
            self.run(caller, origin["method"], context, origin["account"], origin["params"])
        return meta, data

    def call(self, caller: Caller, name: str, context: str, account: str, params: dict, **extra):
        started = time.monotonic()
        error = ""
        try:
            return self._call(caller, name, context, account, params, **extra)
        except AppError as exc:
            error = exc.code
            raise
        except Exception:
            error = "upstream_failure"
            raise
        finally:
            event(
                principal=caller.principal,
                context=context if context in caller.policy.contexts else "unknown",
                account=account if account in caller.policy.accounts else "unknown",
                method=REGISTRY[name].id if name in REGISTRY else name,
                generation=caller.generation,
                started=started,
                decision="denied" if error else "allowed",
                error=error,
            )

    def _call(self, caller: Caller, name: str, context: str, account: str, params: dict, **extra):
        if name in REGISTRY:
            method_id = REGISTRY[name].id
            authorize(caller.policy, caller.principal, context, account, method_id)
            validate_params(REGISTRY[name], params)
            if method_id == "gmail.users.drafts.update":
                current = self.run(
                    caller,
                    "gmail.users.drafts.get",
                    context,
                    account,
                    {"userId": "me", "id": params["id"], "format": "raw"},
                )
                if gmail.revision(gmail.decode_raw(current["message"]["raw"])) != extra.get(
                    "expected_revision"
                ):
                    raise AppError("conflict", "An unchanged draft revision is required", 409)
            if method_id == "gmail.users.drafts.get":
                params = {**params, "format": "raw"}
            result = self.run(caller, method_id, context, account, params)
            if method_id == "gmail.users.messages.attachments.get":
                data = base64.urlsafe_b64decode(result["data"] + "=" * (-len(result["data"]) % 4))
                return self.artifacts.create(
                    caller.principal,
                    context,
                    data,
                    extra.get("filename", "attachment"),
                    origin=Origin(
                        account,
                        "gmail.users.messages.get",
                        {"userId": "me", "id": params["messageId"], "format": "minimal"},
                        ("gmail.users.messages.attachments.get",),
                    ),
                )
            if method_id == "gmail.users.drafts.get":
                return gmail.summarize(result)
        elif name == "gmail_attachment_download":
            message = self.run(
                caller,
                "gmail.users.messages.get",
                context,
                account,
                {"userId": "me", "id": params["message_id"], "format": "full"},
            )

            def find_part(part):
                if part.get("partId") == params["part_id"]:
                    return part
                for child in part.get("parts", []):
                    found = find_part(child)
                    if found:
                        return found
                return None

            part = find_part(message.get("payload", {}))
            if part is None:
                raise AppError("not_found", "Message part not found", 404)
            body = part.get("body", {})
            required: tuple[str, ...] = ()
            if body.get("attachmentId"):
                body = self.run(
                    caller,
                    "gmail.users.messages.attachments.get",
                    context,
                    account,
                    {"userId": "me", "messageId": params["message_id"], "id": body["attachmentId"]},
                )
                required = ("gmail.users.messages.attachments.get",)
            raw = body.get("data", "")
            data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
            result = self.artifacts.create(
                caller.principal,
                context,
                data,
                part.get("filename") or "attachment",
                part.get("mimeType", "application/octet-stream"),
                Origin(
                    account,
                    "gmail.users.messages.get",
                    {"userId": "me", "id": params["message_id"], "format": "minimal"},
                    required,
                ),
            )
        elif name == "gmail_draft_compose":
            draft_id = params.get("draft_id")
            method = "gmail.users.drafts.update" if draft_id else "gmail.users.drafts.create"
            authorize(caller.policy, caller.principal, context, account, method)
            existing = (
                self.run(
                    caller,
                    "gmail.users.drafts.get",
                    context,
                    account,
                    {"userId": "me", "id": draft_id, "format": "raw"},
                )
                if draft_id
                else None
            )
            reply = (
                self.run(
                    caller,
                    "gmail.users.messages.get",
                    context,
                    account,
                    {"userId": "me", "id": params["reply_to_message_id"], "format": "raw"},
                )
                if params.get("reply_to_message_id")
                else None
            )
            attachments = [
                self.artifact(caller, context, ref) for ref in params.get("add_file_refs", [])
            ]
            body = gmail.compose(
                {**params, "own_email": caller.policy.accounts[account].expected_email},
                existing,
                reply,
                attachments,
            )
            if len(body["message"]["raw"]) > 30_000_000:
                raise AppError("too_large", "Composed message exceeds size limit", 413)
            args = {"userId": "me", "body": body}
            if draft_id:
                # Re-read immediately before the write; Gmail has no atomic draft CAS.
                latest = self.run(
                    caller,
                    "gmail.users.drafts.get",
                    context,
                    account,
                    {"userId": "me", "id": draft_id, "format": "raw"},
                )
                if existing is None or latest["message"]["raw"] != existing["message"]["raw"]:
                    raise AppError("conflict", "Draft changed during editing", 409)
                args["id"] = draft_id
            result = self.run(caller, method, context, account, args)
        elif name == "drive_upload":
            meta, data = self.artifact(caller, context, params["file_ref"])
            method = "drive.files.update" if params.get("file_id") else "drive.files.create"
            body = params.get("metadata", {"name": meta["filename"]})
            upload_args: dict = {
                "body": body,
                "fields": "id,name,mimeType,version",
                "supportsAllDrives": True,
            }
            if params.get("file_id"):
                upload_args["fileId"] = params["file_id"]
            result = self.run(
                caller,
                method,
                context,
                account,
                upload_args,
                MediaIoBaseUpload(
                    io.BytesIO(data),
                    mimetype=meta["mime_type"],
                    chunksize=256 * 1024,
                    resumable=True,
                ),
            )
        elif name == "drive_download":
            file_id = params["file_id"]
            visited: set[str] = set()
            for _ in range(8):
                if file_id in visited:
                    raise AppError("invalid_input", "Drive shortcut cycle", 400)
                visited.add(file_id)
                meta = self.run(
                    caller,
                    "drive.files.get",
                    context,
                    account,
                    {
                        "fileId": file_id,
                        "fields": "id,name,mimeType,shortcutDetails",
                        "supportsAllDrives": True,
                    },
                )
                if meta["mimeType"] != "application/vnd.google-apps.shortcut":
                    break
                file_id = meta["shortcutDetails"]["targetId"]
            else:
                raise AppError("invalid_input", "Drive shortcut chain is too deep", 400)
            if meta["mimeType"] == "application/vnd.google-apps.folder":
                raise AppError("invalid_input", "List a folder rather than downloading it", 400)
            method = (
                "drive.files.export"
                if meta["mimeType"].startswith("application/vnd.google-apps.")
                else "drive.files.get"
            )
            _, binding = authorize(caller.policy, caller.principal, context, account, method)
            client = self.clients.build(caller.policy, account, binding, "drive")
            try:
                if method.endswith("export"):
                    mime = params.get("export_mime_type", "application/pdf")
                    request = client.files().export_media(fileId=file_id, mimeType=mime)
                else:
                    mime = meta["mimeType"]
                    request = client.files().get_media(fileId=file_id, supportsAllDrives=True)
                data = drive.download(request, self.artifacts.limit)
            finally:
                client.close()
            result = self.artifacts.create(
                caller.principal,
                context,
                data,
                meta["name"],
                mime,
                Origin(
                    account,
                    "drive.files.get",
                    {"fileId": file_id, "fields": "id", "supportsAllDrives": True},
                    (method,),
                ),
            )
        else:
            raise forbidden()
        if len(json.dumps(result).encode()) > self.result_limit:
            raise AppError(
                "too_large", "Result too large; use fields, smaller pages, or file transfer", 413
            )
        return result
