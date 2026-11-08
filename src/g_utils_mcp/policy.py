"""The permission filter: who may call which tool on which account.

Policy file (YAML in Cloud Storage), version 2:

    version: 2
    principals:
      claude-cloud: {token_sha256: [<hex sha256 of the bearer token>]}
    accounts:
      mailbox: {email: mailbox@example.net, secret: projects/P/secrets/S/versions/latest}
    grants:
      claude-cloud:
        mailbox:
          allow: [gmail_users_messages_list, gmail_draft_compose]
          deny: [gmail_users_messages_send]

Tool names are Google method ids with "." replaced by "_" (plus a few helper tools).
Anything not explicitly allowed is denied, and deny wins over allow.
"""

import hashlib
import hmac
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import yaml
from jsonschema import Draft7Validator
from yaml.tokens import AliasToken, AnchorToken, TagToken

from . import utils
from .utils import AppError

NAME = r"^[a-zA-Z0-9_-]{1,80}$"
TOOL = r"^[a-z][a-zA-Z0-9_]{1,120}$"
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["version", "principals", "accounts", "grants"],
    "properties": {
        "version": {"const": 2},
        "revision": {"type": "string", "maxLength": 200},
        "principals": {
            "type": "object",
            "propertyNames": {"pattern": NAME},
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "required": ["token_sha256"],
                "properties": {
                    "token_sha256": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    }
                },
            },
        },
        "accounts": {
            "type": "object",
            "propertyNames": {"pattern": NAME},
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "required": ["email", "secret"],
                "properties": {
                    "email": {"type": "string", "pattern": "^[^@\\s]+@[^@\\s]+$"},
                    "secret": {"type": "string", "pattern": "^" + utils.SECRET_REF + "$"},
                },
            },
        },
        "grants": {
            "type": "object",
            "propertyNames": {"pattern": NAME},
            "additionalProperties": {
                "type": "object",
                "propertyNames": {"pattern": NAME},
                "additionalProperties": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "allow": {"type": "array", "items": {"type": "string", "pattern": TOOL}},
                        "deny": {"type": "array", "items": {"type": "string", "pattern": TOOL}},
                    },
                },
            },
        },
    },
}


@dataclass(frozen=True)
class Caller:
    principal: str
    policy: dict
    generation: int


# --- Loading -----------------------------------------------------------------------------------


class _Loader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys (merge keys have no constructor and fail)."""


def _mapping(loader: _Loader, node: yaml.MappingNode) -> dict:
    out: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in out:
            raise ValueError("Duplicate, merge or non-string YAML key")
        out[key] = loader.construct_object(value_node, deep=True)
    return out


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def parse(data: bytes, known: set[str]) -> dict:
    """Parse and validate a policy. `known` is the set of grantable tool names."""
    if len(data) > 1_000_000:
        raise ValueError("Policy exceeds size limit")
    try:
        if any(isinstance(t, AliasToken | AnchorToken | TagToken) for t in yaml.scan(data)):
            raise ValueError("YAML aliases, anchors and tags are not supported")
        policy = yaml.load(data, Loader=_Loader)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from None
    error = next(Draft7Validator(SCHEMA).iter_errors(policy), None)
    if error is not None:
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        raise ValueError(f"Invalid policy at {where}: {error.message}")
    for principal, accounts in policy["grants"].items():
        if principal not in policy["principals"]:
            raise ValueError(f"Grant for unknown principal {principal}")
        for account, grant in accounts.items():
            if account not in policy["accounts"]:
                raise ValueError(f"Grant for unknown account {account}")
            unknown = set(grant.get("allow", [])) - known
            if unknown:
                raise ValueError(f"Unknown or unimplemented tools in allow: {sorted(unknown)}")
    return policy


def loader(blob: Any, known: set[str]) -> Callable[[], tuple[dict, int]]:
    """Return current() -> (policy, generation).

    Each call reads only the object's metadata. The body is downloaded and parsed again only
    when the generation changed, so a published revocation applies to the next request.
    Any failure fails closed.
    """
    lock = threading.Lock()
    state: dict[str, Any] = {"generation": None, "policy": None}

    def current() -> tuple[dict, int]:
        try:
            with lock:
                blob.reload()
                generation = int(blob.generation)
                if generation != state["generation"]:
                    data = blob.download_as_bytes(if_generation_match=generation)
                    state["policy"], state["generation"] = parse(data, known), generation
                    utils.log(event="policy_loaded", generation=generation)
                return state["policy"], generation
        except Exception:
            raise AppError("policy_unavailable", "Current policy is unavailable", 503) from None

    return current


# --- Checks ------------------------------------------------------------------------------------


def authenticate(policy: dict, authorization: str) -> str:
    """Map `Bearer <principal>.<random>` to a principal by comparing token digests."""
    scheme, _, token = authorization.partition(" ")
    name, _, random_part = token.partition(".")
    entry = policy["principals"].get(name)
    if scheme.lower() != "bearer" or not entry or len(random_part) < 43:
        raise AppError("unauthenticated", "Authentication required", 401)
    digest = hashlib.sha256(token.encode()).hexdigest()
    if not any(hmac.compare_digest(digest, d) for d in entry["token_sha256"]):
        raise AppError("unauthenticated", "Authentication required", 401)
    return name


def allowed(policy: dict, principal: str, account: str, tool: str) -> bool:
    grant = policy["grants"].get(principal, {}).get(account)
    return bool(grant) and tool in grant.get("allow", []) and tool not in grant.get("deny", [])


def check(caller: Caller, account: str, tool: str) -> dict:
    """Raise unless `tool` is allowed (and not denied) for this caller on `account`."""
    if account not in caller.policy["accounts"]:
        raise AppError()
    if not allowed(caller.policy, caller.principal, account, tool):
        raise AppError()
    return caller.policy["accounts"][account]


def tools_for(caller: Caller) -> dict[str, list[str]]:
    """Account alias -> effective (allowed minus denied) tool names, for this caller only."""
    out = {}
    for account, grant in caller.policy["grants"].get(caller.principal, {}).items():
        names = [t for t in grant.get("allow", []) if t not in grant.get("deny", [])]
        if names and account in caller.policy["accounts"]:
            out[account] = sorted(names)
    return out


DOCS_REQUESTS = {
    "insertText",
    "deleteContentRange",
    "replaceAllText",
    "updateTextStyle",
    "updateParagraphStyle",
    "insertTable",
    "insertTableRow",
    "insertTableColumn",
    "deleteTableRow",
    "deleteTableColumn",
    "updateTableCellStyle",
}


def check_args(method: str, params: dict) -> None:
    """Fixed argument rules that hold for every grant (on top of the schema check)."""
    if next(Draft7Validator(utils.method_schema(method)).iter_errors(params), None):
        raise AppError("invalid_input", "Arguments do not match the method schema", 400)
    for key in ("maxResults", "pageSize"):
        if key in params and not 1 <= params[key] <= 100:
            raise AppError("invalid_input", "Page size must be between 1 and 100", 400)
    body = params.get("body", {})
    if method.startswith("gmail."):
        if method.endswith(".modify") and set(body.get("addLabelIds", [])) & {"TRASH", "SPAM"}:
            raise AppError()
        if (
            method.startswith("gmail.users.labels.")
            and method.rsplit(".", 1)[1] in ("delete", "update", "patch")
            and not params.get("id", "").startswith("Label_")
        ):
            raise AppError("invalid_input", "Only user labels may be edited or deleted", 400)
    if method in ("drive.files.create", "drive.files.update"):
        fields = {"name", "description", "mimeType"} | (
            {"parents"} if method.endswith("create") else set()
        )
        if set(body) - fields or "addParents" in params or "removeParents" in params:
            raise AppError()
    if method == "docs.documents.create" and set(body) - {"title"}:
        raise AppError()
    if method == "docs.documents.batchUpdate":
        requests = body.get("requests", [])
        if not 1 <= len(requests) <= 100:
            raise AppError("invalid_input", "Provide between 1 and 100 edit requests", 400)
        if not body.get("writeControl", {}).get("requiredRevisionId"):
            raise AppError("invalid_input", "An expected document revision is required", 400)
        if any(len(r) != 1 or next(iter(r)) not in DOCS_REQUESTS for r in requests):
            raise AppError()


def tool_name(method: str) -> str:
    return method.replace(".", "_")


def run(caller: Caller, account: str, method: str, params: dict, media=None, download=False) -> Any:
    """The only path to Google: check grant, check arguments, load credentials, call."""
    target = check(caller, account, tool_name(method))
    if method.startswith("gmail."):
        if params.get("userId", "me") != "me":
            raise AppError()
        params = {**params, "userId": "me"}
    check_args(method, params)
    client = utils.service(method.split(".")[0], utils.credentials(account, target["secret"]))
    try:
        return utils.call(client, method, params, media=media, download=download)
    finally:
        client.close()


def get_file(caller: Caller, ref: str, tool: str) -> tuple[dict, bytes]:
    """Read a temporary file; files fetched from Google need their source tools still allowed."""
    meta, data = utils.get_file(caller.principal, ref, tool)
    for name in meta.get("requires", []):
        check(caller, meta["account"], name)
    return meta, data
