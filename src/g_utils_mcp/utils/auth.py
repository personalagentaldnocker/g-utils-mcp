"""Who is calling, what they may do, and the Google credentials to do it with.

Policy (GCS, no secrets) decides; the single secret only holds credentials. Deny wins.
"""

import hmac
import re
import threading
import time
from collections.abc import Iterable
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from yaml.tokens import AliasToken, AnchorToken, TagToken

from ..config import IDENTITY_SCOPES, SCOPES, SECRET_CACHE_SECONDS
from ..services import drive, gmail
from .helpers import AppError, forbidden, gcs_generation, gcs_read, secret_read

IMPLEMENTED = set(gmail.METHODS) | set(drive.METHODS) | set(drive.INTERNAL)
DOCS_REQUESTS = [
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
]

# --- Policy file ---


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Principal(Strict):
    enabled: bool = True
    allowed_contexts: list[str]


class Account(Strict):
    enabled: bool = False
    expected_email: str
    services: list[Literal["gmail", "drive"]] = Field(min_length=1)


class Constraints(Strict):
    forbidden_added_label_ids: list[str] = Field(default_factory=lambda: ["TRASH", "SPAM"])
    allowed_docs_requests: list[str] = Field(default_factory=lambda: DOCS_REQUESTS.copy())


class Grant(Strict):
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)


class Context(Strict):
    grants: dict[str, dict[str, Grant]] = Field(default_factory=dict)


class Policy(Strict):
    schema_version: Literal[1] = 1
    policy_revision: str
    default_effect: Literal["deny"] = "deny"
    principals: dict[str, Principal] = Field(default_factory=dict)
    accounts: dict[str, Account] = Field(default_factory=dict)
    contexts: dict[str, Context] = Field(default_factory=dict)

    @model_validator(mode="after")
    def references(self) -> Self:
        for mapping in (self.principals, self.accounts, self.contexts):
            if any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", key) for key in mapping):
                raise ValueError("Invalid policy alias")
        for principal in self.principals.values():
            if any(c not in self.contexts for c in principal.allowed_contexts):
                raise ValueError("Unknown context in allowed_contexts")
        for context in self.contexts.values():
            for principal_id, grants in context.grants.items():
                if principal_id not in self.principals:
                    raise ValueError("Unknown grant principal")
                for account_id, grant in grants.items():
                    if account_id not in self.accounts:
                        raise ValueError("Unknown grant account")
                    if any("*" in m for m in grant.allow + grant.deny):
                        raise ValueError("Wildcard grants are not supported")
                    if set(grant.allow) - IMPLEMENTED:
                        raise ValueError("Unimplemented or unknown method in allow list")
                    if set(grant.constraints.allowed_docs_requests) - set(DOCS_REQUESTS):
                        raise ValueError("Unsupported Docs operation")
        return self


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key == "<<" or key in mapping:
            raise ValueError("Duplicate, merge or non-string YAML key")
        mapping[key] = loader.construct_object(value_node)
    return mapping


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def parse_policy(data: bytes) -> Policy:
    if len(data) > 1_000_000:
        raise ValueError("Policy exceeds size limit")
    if any(isinstance(t, AliasToken | AnchorToken | TagToken) for t in yaml.scan(data)):
        raise ValueError("YAML aliases, anchors and tags are not supported")
    return Policy.model_validate(yaml.load(data, Loader=_UniqueLoader))


_lock = threading.Lock()
_policy: dict = {"generation": None, "policy": None}
_secret: dict = {"at": 0.0, "value": None}


def current_policy(uri: str) -> Policy:
    """Check the generation on every call; download and parse only when it changed."""
    try:
        generation = gcs_generation(uri)
        with _lock:
            if generation and generation == _policy["generation"]:
                return _policy["policy"]
        data, generation = gcs_read(uri)
        policy = parse_policy(data)
    except Exception:
        raise AppError("policy_unavailable", "Current policy is unavailable", 503) from None
    with _lock:
        _policy.update(generation=generation, policy=policy)
    return policy


def current_secret(name: str) -> dict:
    with _lock:
        if _secret["value"] is not None and time.monotonic() - _secret["at"] < SECRET_CACHE_SECONDS:
            return _secret["value"]
    value = secret_read(name)
    with _lock:
        _secret.update(at=time.monotonic(), value=value)
    return value


# --- Decisions ---


def authenticate(authorization: str, policy: Policy, secret: dict) -> str:
    """Bearer token -> enabled principal, compared in constant time against the secret."""
    scheme, _, token = authorization.partition(" ")
    found = ""
    for principal_id, entry in secret.get("principals", {}).items():
        if hmac.compare_digest(token.encode(), str(entry.get("token", "")).encode()):
            found = principal_id
    principal = policy.principals.get(found)
    if scheme.lower() != "bearer" or len(token) < 32 or not principal or not principal.enabled:
        raise AppError("unauthenticated", "Authentication required", 401)
    return found


def service_of(method_id: str) -> str:
    return "gmail" if method_id.startswith("gmail.") else "drive"


def authorize(policy: Policy, principal_id: str, context: str, account: str, method: str) -> Grant:
    principal = policy.principals.get(principal_id)
    target = policy.accounts.get(account)
    ctx = policy.contexts.get(context)
    if not principal or not principal.enabled or not target or not target.enabled or not ctx:
        raise forbidden()
    if context not in principal.allowed_contexts or service_of(method) not in target.services:
        raise forbidden()
    grant = ctx.grants.get(principal_id, {}).get(account)
    if not grant or method not in grant.allow or method in grant.deny:
        raise forbidden()
    return grant


def permitted(policy: Policy, principal_id: str, methods: list[str]) -> bool:
    """Whether any context/account grants any of `methods` (decides which tools are listed)."""
    for context in policy.contexts:
        for account in policy.accounts:
            for method in methods:
                try:
                    authorize(policy, principal_id, context, account, method)
                    return True
                except AppError:
                    pass
    return False


def constrain(method: str, params: dict, grant: Grant) -> None:
    """Argument-level rules on top of the method grant."""
    body = params.get("body", {})
    if method.startswith("gmail."):
        if params.get("userId", "me") != "me":
            raise forbidden()
        if method.endswith(".modify") and set(body.get("addLabelIds", [])) & set(
            grant.constraints.forbidden_added_label_ids
        ):
            raise forbidden()
        if (
            method.startswith("gmail.users.labels.")
            and method.rsplit(".", 1)[1] in ("delete", "update", "patch")
            and not params.get("id", "").startswith("Label_")
        ):
            raise AppError("invalid_input", "Only user labels may be edited or deleted", 400)
    if method in ("drive.files.create", "drive.files.update"):
        allowed = {"name", "description", "mimeType"} | (
            {"parents"} if "create" in method else set()
        )
        if set(body) - allowed or "addParents" in params or "removeParents" in params:
            raise forbidden()
    if method == "docs.documents.create" and set(body) - {"title"}:
        raise forbidden()
    if method == "docs.documents.batchUpdate":
        requests = body.get("requests", [])
        if not requests or len(requests) > 100:
            raise AppError("invalid_input", "Provide between 1 and 100 edit requests", 400)
        if not body.get("writeControl", {}).get("requiredRevisionId"):
            raise AppError("invalid_input", "An expected document revision is required", 400)
        allowed_requests = grant.constraints.allowed_docs_requests
        if any(len(r) != 1 or next(iter(r)) not in allowed_requests for r in requests):
            raise forbidden()


# --- Google credentials ---

_credentials: dict[tuple, object] = {}


def scopes_for(services: Iterable[str]) -> list[str]:
    return IDENTITY_SCOPES + [scope for service in services for scope in SCOPES[service]]


def credentials(policy: Policy, secret: dict, account: str, service: str):
    """Credentials for one account; the access token is cached until shortly before expiry."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    entry = secret.get("accounts", {}).get(account, {})
    client = secret.get("oauth_client", {})
    needed = SCOPES[service]
    if (
        not entry.get("refresh_token")
        or entry.get("email", "").lower() != policy.accounts[account].expected_email.lower()
        or not set(needed) <= set(entry.get("scopes", []))
    ):
        raise AppError("reauth_required", "Sign the Google account in again", 401)
    key = (account, entry["refresh_token"], client.get("client_id"))
    with _lock:
        creds = _credentials.get(key)
        if creds is None:
            creds = Credentials(
                token=None,
                refresh_token=entry["refresh_token"],
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client.get("client_id"),
                client_secret=client.get("client_secret"),
                scopes=entry["scopes"],
            )
            for stale in [k for k in _credentials if k[0] == account]:
                del _credentials[stale]  # a new sign-in replaces the old token
            _credentials[key] = creds
        if not creds.valid:  # type: ignore[attr-defined]
            try:
                creds.refresh(Request())  # type: ignore[attr-defined]
            except RefreshError:
                raise AppError("reauth_required", "Sign the Google account in again", 401) from None
    return creds
