"""Cloud Storage, Secret Manager, Google API Discovery and the generic method call."""

import base64
import copy
import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from urllib.parse import urlsplit

from jsonschema import Draft7Validator

from .. import config

VERSIONS = {"gmail": "v1", "drive": "v3", "docs": "v1"}
READ_VERBS = ("get", "list", "getProfile", "export")


class AppError(Exception):
    """Public, content-free error with a stable code."""

    def __init__(self, code: str, message: str, status: int = 403):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def forbidden() -> AppError:
    return AppError("forbidden", "Operation is not permitted")


# --- Cloud Storage (policy file) ---


@cache
def _bucket(name: str):
    from google.cloud import storage  # type: ignore[attr-defined]

    return storage.Client().bucket(name)


def _blob(uri: str):
    parts = urlsplit(uri)
    return _bucket(parts.netloc).blob(parts.path.lstrip("/"))


def gcs_generation(uri: str) -> int:
    """Generation of the object (metadata only), 0 if it does not exist."""
    from google.api_core.exceptions import NotFound

    blob = _blob(uri)
    try:
        blob.reload()
    except NotFound:
        return 0
    return int(blob.generation)


def gcs_read(uri: str) -> tuple[bytes, int]:
    blob = _blob(uri)
    blob.reload()
    generation = int(blob.generation)
    return blob.download_as_bytes(if_generation_match=generation), generation


def gcs_write(uri: str, data: bytes, generation: int) -> int:
    """Write only if the object is still at `generation` (0 = must not exist yet)."""
    from google.api_core.exceptions import PreconditionFailed

    blob = _blob(uri)
    try:
        blob.upload_from_string(data, if_generation_match=generation)
    except PreconditionFailed:
        raise AppError("conflict", "Policy changed since it was read; pull again", 409) from None
    return int(blob.generation)


# --- Secret Manager (the single secret) ---


@cache
def _secrets():
    from google.cloud import secretmanager

    return secretmanager.SecretManagerServiceClient()


def secret_read(name: str) -> dict:
    """Latest version as JSON, {} when the secret has no version yet."""
    from google.api_core.exceptions import FailedPrecondition, NotFound

    try:
        response = _secrets().access_secret_version(name=name + "/versions/latest")
    except (NotFound, FailedPrecondition):
        return {}
    return json.loads(response.payload.data)


def secret_write(name: str, value: dict) -> None:
    payload = json.dumps(value, sort_keys=True).encode()
    _secrets().add_secret_version(request={"parent": name, "payload": {"data": payload}})


# --- Files ---


def b64decode(data: str, limit: int) -> bytes:
    if len(data) > limit * 4 // 3 + 8:
        raise AppError("too_large", "File exceeds the size limit", 413)
    raw = base64.urlsafe_b64decode(
        data.replace("+", "-").replace("/", "_") + "=" * (-len(data) % 4)
    )
    if len(raw) > limit:
        raise AppError("too_large", "File exceeds the size limit", 413)
    return raw


@dataclass(frozen=True)
class User:
    """Who a hand-written tool acts for: the agent (owns file refs) and the account email."""

    principal: str
    email: str


def _file_blob(ref: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", ref):
        raise AppError("not_found", "Unknown or expired file_ref", 404)
    return _bucket(config.temp_bucket()).blob("files/" + ref)


def file_store(principal: str, data: bytes, name: str, mime_type: str) -> str:
    """Put file contents in the temporary bucket; the ref works only for `principal`."""
    if len(data) > config.MAX_FILE_BYTES:
        raise AppError("too_large", "File exceeds the size limit", 413)
    ref = secrets.token_urlsafe(32)
    blob = _file_blob(ref)
    blob.metadata = {"principal": principal, "filename": name}
    blob.upload_from_string(data, content_type=mime_type, if_generation_match=0)
    return ref


def file_load(principal: str, ref: str) -> tuple[bytes, str, str]:
    from google.api_core.exceptions import NotFound

    blob = _file_blob(ref)
    try:
        blob.reload()
    except NotFound:
        raise AppError("not_found", "Unknown or expired file_ref", 404) from None
    age = time.time() - blob.time_created.timestamp()
    if (blob.metadata or {}).get("principal") != principal or age > config.FILE_REF_SECONDS:
        raise AppError("not_found", "Unknown or expired file_ref", 404)
    if (blob.size or 0) > config.MAX_FILE_BYTES:
        raise AppError("too_large", "File exceeds the size limit", 413)
    data = blob.download_as_bytes(if_generation_match=blob.generation)
    return (
        data,
        blob.metadata.get("filename", "file"),
        blob.content_type or "application/octet-stream",
    )


def file_out(user: User, data: bytes, name: str, mime_type: str) -> dict:
    """Small files inline as base64, larger ones as a file_ref to GET /files/<ref>."""
    result = {
        "filename": name,
        "mime_type": mime_type,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    if len(data) <= config.INLINE_FILE_BYTES:
        return {**result, "data_base64": base64.b64encode(data).decode()}
    ref = file_store(user.principal, data, name, mime_type)
    return {**result, "file_ref": ref, "download": f"GET /files/{ref} with your MCP token"}


def file_in(user: User, spec: dict) -> tuple[bytes, str, str]:
    """File from `data_base64` (inline) or `file_ref` (from POST /files); returns data, name, type."""
    if "file_ref" in spec:
        data, name, mime_type = file_load(user.principal, spec["file_ref"])
    elif "data_base64" in spec:
        data = b64decode(spec["data_base64"], config.INLINE_FILE_BYTES)
        name, mime_type = "file", "application/octet-stream"
    else:
        raise AppError("invalid_input", "Give data_base64 or file_ref", 400)
    return data, spec.get("filename", name), spec.get("mime_type", mime_type)


# --- Discovery: input schemas and API clients ---


@cache
def discovery(api: str) -> str:
    path = files("g_utils_mcp").joinpath(f"discovery/{api}.{VERSIONS[api]}.json")
    return path.read_text()


@cache
def _methods(api: str) -> dict[str, dict]:
    found: dict[str, dict] = {}

    def walk(node):
        for method in node.get("methods", {}).values():
            found[method["id"]] = method
        for resource in node.get("resources", {}).values():
            walk(resource)

    walk(json.loads(discovery(api)))
    return found


def _normalize(node: dict) -> dict:
    """Turn a Discovery schema node into JSON Schema (closed objects, numeric bounds)."""
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
def method_schema(method_id: str) -> dict:
    """JSON Schema for the `params` of a Google method, with only the definitions it uses."""
    api = method_id.split(".")[0]
    method = _methods(api)[method_id]
    definitions = {k: _normalize(v) for k, v in json.loads(discovery(api))["schemas"].items()}
    params = {k: _normalize(v) for k, v in method.get("parameters", {}).items()}
    required = [k for k, v in method.get("parameters", {}).items() if v.get("required")]
    if "request" in method:
        params["body"] = _normalize(method["request"])
        required.append("body")
    params["fields"] = {"type": "string", "maxLength": 1000}
    needed: dict[str, dict] = {}

    def collect(node):
        if isinstance(node, dict):
            ref = node.get("$ref", "").removeprefix("#/definitions/")
            if ref in definitions and ref not in needed:
                needed[ref] = definitions[ref]
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
        "definitions": needed,
    }


def validate(method_id: str, params: dict) -> None:
    if next(Draft7Validator(method_schema(method_id)).iter_errors(params), None):
        raise AppError("invalid_input", "Arguments do not match the method schema", 400)
    for key in ("maxResults", "pageSize"):
        if key in params and not 1 <= params[key] <= 100:
            raise AppError("invalid_input", "Page size must be between 1 and 100", 400)


def build_client(api: str, credentials):
    from googleapiclient.discovery import build_from_document

    return build_from_document(discovery(api), credentials=credentials)


def call(client, method_id: str, params: dict, media=None):
    """Call e.g. `gmail.users.messages.list` on a built client; map Google errors."""
    from google.auth.exceptions import GoogleAuthError
    from googleapiclient.errors import HttpError

    resource = client
    *path, verb = method_id.split(".")[1:]
    for part in path:
        resource = getattr(resource, part)()
    args = dict(params)
    write = verb not in READ_VERBS
    if media == "download":  # file content instead of metadata: get_media / export_media
        verb += "_media"
    elif media is not None:
        args["media_body"] = media
    try:
        result = getattr(resource, verb)(**args).execute(num_retries=0)
    except HttpError as exc:
        status = int(exc.resp.status)
        if status == 429:
            raise AppError("rate_limited", "Google quota exceeded; retry later", 429) from None
        if status in (401, 403, 404):
            raise AppError("upstream_denied", "Google denied the operation", status) from None
        if status == 400:
            raise AppError("invalid_input", "Google rejected the request", 400) from None
        if status in (409, 412):
            raise AppError("conflict", "Resource changed; read again", 409) from None
        if write:
            raise AppError(
                "uncertain_write", "Write outcome is uncertain; check before retrying", 502
            ) from None
        raise AppError("upstream_failure", "Google operation failed", 502) from None
    except GoogleAuthError:
        raise AppError("reauth_required", "Sign the Google account in again", 401) from None
    except (TimeoutError, OSError):
        code = "uncertain_write" if write else "upstream_failure"
        raise AppError(code, "Request to Google failed", 502) from None
    return {"success": True} if result in (None, "") else result
