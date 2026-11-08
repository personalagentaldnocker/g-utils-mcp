"""Cloud Storage, Secret Manager, Google API and logging helpers."""

import copy
import hashlib
import io
import json
import logging
import os
import re
import secrets
import time
from functools import cache
from typing import Any

from google.auth.exceptions import GoogleAuthError, RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

logger = logging.getLogger("g_utils_mcp")
SECRET_REF = r"projects/([a-zA-Z0-9_-]+)/secrets/[a-zA-Z0-9_-]+/versions/(latest|[0-9]+)"
APIS = {"gmail": "v1", "drive": "v3", "docs": "v1"}
TRANSFER_LIMIT = int(os.environ.get("MAX_TRANSFER_BYTES", 20_000_000))
RESULT_LIMIT = 1_000_000
FILE_TTL = 1800
READS = ("get", "list", "getProfile", "export")


class AppError(Exception):
    """Content-free error with a stable code; the only text a caller ever sees."""

    def __init__(self, code: str = "forbidden", message: str = "Not permitted", status: int = 403):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def log(**fields: Any) -> None:
    """One JSON line of allowlisted fields. Never pass arguments, bodies or tokens."""
    logger.warning(json.dumps({"ts": round(time.time(), 3), **fields}))


# --- Cloud Storage -----------------------------------------------------------------------------


@cache
def bucket(name: str):
    from google.cloud import storage  # type: ignore[attr-defined]

    return storage.Client().bucket(name)


def temp_bucket():
    return bucket(os.environ["TEMP_BUCKET"])


def put_file(
    principal: str,
    account: str,
    data: bytes,
    name: str,
    mime: str,
    tool: str,
    requires: tuple[str, ...] = (),
) -> dict:
    """Store bytes in the temporary bucket and return a short-lived reference to them."""
    if len(data) > TRANSFER_LIMIT:
        raise AppError("too_large", "File exceeds transfer limit", 413)
    name = re.sub(r"[^\w. ()-]", "_", name.replace("\\", "/").rsplit("/", 1)[-1], flags=re.ASCII)
    if not re.fullmatch(r"[\w!#$&^.+-]+/[\w!#$&^.+-]+", mime, flags=re.ASCII):
        mime = "application/octet-stream"
    ref = secrets.token_urlsafe(32)
    meta = {
        "file_ref": ref,
        "filename": name[:180] or "file",
        "mime_type": mime,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "expires": time.time() + FILE_TTL,
    }
    blob = temp_bucket().blob("files/" + ref)
    private = {"principal": principal, "account": account, "requires": list(requires)}
    blob.metadata = {"meta": json.dumps({**meta, **private})}
    blob.upload_from_string(data, content_type=mime, if_generation_match=0)
    log(event="file_put", principal=principal, account=account, tool=tool, **_public(meta))
    return meta


def get_file(principal: str, ref: str, tool: str) -> tuple[dict, bytes]:
    """Return (meta, bytes) for a reference the same principal created and that has not expired."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", ref):
        raise AppError()
    blob = temp_bucket().get_blob("files/" + ref)
    if blob is None or blob.size is None or blob.size > TRANSFER_LIMIT:
        raise AppError("not_found", "File not found", 404)
    meta = json.loads((blob.metadata or {})["meta"])
    if meta["principal"] != principal or meta["expires"] <= time.time():
        raise AppError()
    data = blob.download_as_bytes(if_generation_match=blob.generation)
    if hashlib.sha256(data).hexdigest() != meta["sha256"]:
        raise AppError("unavailable", "File integrity check failed", 503)
    log(event="file_get", principal=principal, account=meta["account"], tool=tool, **_public(meta))
    return meta, data


def _public(meta: dict) -> dict:
    return {k: meta[k] for k in ("file_ref", "size", "sha256")}


# --- Secret Manager and Google credentials ------------------------------------------------------


@cache
def _secret_client():
    from google.cloud import secretmanager

    return secretmanager.SecretManagerServiceClient()


def read_secret(ref: str) -> bytes:
    """Read a secret version, but only from the projects the deployment allows."""
    match = re.fullmatch(SECRET_REF, ref)
    allowed = json.loads(os.environ.get("ALLOWED_SECRET_PROJECTS", "[]"))
    if not match or match[1] not in allowed:
        raise AppError()
    return bytes(_secret_client().access_secret_version(name=ref).payload.data)


_credentials: dict[str, tuple[bytes, Credentials]] = {}


def credentials(account: str, secret_ref: str) -> Credentials:
    """Build OAuth credentials from the account's authorized-user secret.

    google-auth refreshes the access token. The Credentials object is reused while the
    secret payload is unchanged, so a refreshed access token survives between requests.
    """
    raw = read_secret(secret_ref)
    cached = _credentials.get(account)
    if cached and cached[0] == raw:
        return cached[1]
    info = json.loads(raw)
    if info.get("account") != account:
        raise AppError()  # The secret was written for a different account alias.
    creds = Credentials(
        token=None,
        refresh_token=info["refresh_token"],
        token_uri=info.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=info["client_id"],
        client_secret=info["client_secret"],
        scopes=info.get("scopes"),
    )
    _credentials[account] = (raw, creds)
    return creds


def service(api: str, creds: Credentials):
    # Discovery documents ship with google-api-python-client (static_discovery), so the
    # API surface is pinned by the lockfile and no network fetch happens here.
    return build(api, APIS[api], credentials=creds, cache_discovery=False, static_discovery=True)


def call(client, method: str, params: dict, media=None, download=False) -> Any:
    """Run `api.resource.sub.method(**params)` on a built client and map Google errors.

    With download=True the `<method>_media` variant is streamed into a bounded buffer and
    the bytes are returned. Callers authorize `method` first (policy.run does).
    """
    resource = client
    parts = method.split(".")[1:]
    for part in parts[:-1]:
        resource = getattr(resource, part)()
    args = dict(params)
    if media is not None:
        args["media_body"] = media
    try:
        if download:
            return _download(getattr(resource, parts[-1] + "_media")(**args))
        result = getattr(resource, parts[-1])(**args).execute(num_retries=0)
    except HttpError as exc:
        raise google_error(int(exc.resp.status), method) from None
    except RefreshError:
        raise AppError("reauth_required", "Reconnect the Google account", 401) from None
    except GoogleAuthError:
        raise AppError("upstream_failure", "Google authentication failed", 503) from None
    except (TimeoutError, OSError):
        raise google_error(599, method) from None
    return {"success": True} if result in (None, "") else result


class _Bounded(io.BytesIO):
    def write(self, data) -> int:  # type: ignore[override]
        if self.tell() + len(data) > TRANSFER_LIMIT:
            raise AppError("too_large", "File exceeds transfer limit", 413)
        return super().write(data)


def _download(request) -> bytes:
    buffer = _Bounded()
    downloader = MediaIoBaseDownload(buffer, request, chunksize=256 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk(num_retries=0)
    return buffer.getvalue()


def google_error(status: int, method: str) -> AppError:
    write = method.rsplit(".", 1)[-1] not in READS
    if status == 429:
        return AppError("rate_limited", "Google quota exceeded; retry later", 429)
    if status in (401, 403, 404):
        return AppError("upstream_denied", "Google denied the requested operation", status)
    if status == 400:
        return AppError("invalid_input", "Google rejected the request; check arguments", 400)
    if status in (409, 412):
        return AppError("conflict", "Resource revision changed; read again", 409)
    if status >= 500 and write:
        return AppError("uncertain_write", "Write outcome unknown; reconcile before retry", 502)
    return AppError("upstream_failure", "Google operation failed", 502)


# --- Discovery-derived input schemas -------------------------------------------------------------


@cache
def discovery(api: str) -> dict:
    from googleapiclient.discovery_cache import get_static_doc

    return json.loads(get_static_doc(api, APIS[api]) or "{}")


def _find(node: dict, path: list[str]) -> dict:
    for part in path[:-1]:
        node = node["resources"][part]
    return node["methods"][path[-1]]


def _normalize(node: dict) -> dict:
    """Turn a Discovery schema fragment into strict JSON Schema (unknown fields rejected)."""
    node = copy.deepcopy(node)
    if isinstance(node.get("required"), bool):
        node.pop("required")
    if "$ref" in node:
        return {"$ref": "#/definitions/" + node["$ref"]}
    if node.get("type") == "object":
        node.setdefault("properties", {})
        node.setdefault("additionalProperties", False)
    if "properties" in node:
        node["properties"] = {k: _normalize(v) for k, v in node["properties"].items()}
    if "items" in node:
        node["items"] = _normalize(node["items"])
    if isinstance(node.get("additionalProperties"), dict):
        node["additionalProperties"] = _normalize(node["additionalProperties"])
    for key in ("minimum", "maximum"):
        if key in node:
            node[key] = int(node[key])
    return node


@cache
def method_schema(method: str) -> dict:
    """JSON Schema for the `params` of a Google method such as gmail.users.messages.list."""
    api, *path = method.split(".")
    doc = discovery(api)
    spec = _find(doc, path)
    params = {k: _normalize(v) for k, v in spec.get("parameters", {}).items()}
    required = [k for k, v in spec.get("parameters", {}).items() if v.get("required")]
    if "request" in spec:
        params["body"] = _normalize(spec["request"])
        required.append("body")
    params["fields"] = {"type": "string", "maxLength": 1000}
    definitions: dict[str, dict] = {}

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref", "").removeprefix("#/definitions/")
            if ref in doc["schemas"] and ref not in definitions:
                definitions[ref] = _normalize(doc["schemas"][ref])
                collect(definitions[ref])
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(params)
    return {
        "type": "object",
        "properties": params,
        "required": required,
        "additionalProperties": False,
        "definitions": definitions,
    }
