import re
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from yaml.tokens import AliasToken, AnchorToken, TagToken

SECRET_PATTERN = r"^projects/([a-zA-Z0-9_-]+)/secrets/([a-zA-Z0-9_-]+)/versions/(latest|[0-9]+)$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Owner(StrictModel):
    display_name: str


class Principal(StrictModel):
    owner: str
    enabled: bool = True
    credential_digest_secret_refs: list[str] = Field(min_length=1, max_length=3)
    allowed_contexts: list[str]


class OAuthClient(StrictModel):
    client_id: str
    client_secret_ref: str


class ServiceBinding(StrictModel):
    oauth_client: str
    refresh_token_secret_ref: str
    oauth_scopes: list[str] = Field(min_length=1)


class Account(StrictModel):
    owner: str
    enabled: bool = False
    expected_email: str
    google_subject: str = ""
    services: dict[Literal["gmail", "drive"], ServiceBinding]


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


class Constraints(StrictModel):
    forbidden_added_label_ids: list[str] = Field(default_factory=lambda: ["TRASH", "SPAM"])
    allowed_docs_requests: list[str] = Field(default_factory=lambda: DOCS_REQUESTS.copy())


class Grant(StrictModel):
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)


class Context(StrictModel):
    grants: dict[str, dict[str, Grant]] = Field(default_factory=dict)


class Policy(StrictModel):
    schema_version: Literal[1] = 1
    policy_revision: str
    default_effect: Literal["deny"] = "deny"
    owners: dict[str, Owner] = Field(default_factory=dict)
    principals: dict[str, Principal] = Field(default_factory=dict)
    oauth_clients: dict[str, OAuthClient] = Field(default_factory=dict)
    accounts: dict[str, Account] = Field(default_factory=dict)
    contexts: dict[str, Context] = Field(default_factory=dict)

    @model_validator(mode="after")
    def references(self) -> Self:
        from ..registry import IMPLEMENTED

        for mapping in (
            self.owners,
            self.principals,
            self.oauth_clients,
            self.accounts,
            self.contexts,
        ):
            if any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", key) for key in mapping):
                raise ValueError("Invalid policy alias")
        refs = []
        for principal in self.principals.values():
            if principal.owner not in self.owners or any(
                c not in self.contexts for c in principal.allowed_contexts
            ):
                raise ValueError("Invalid principal reference")
            refs.extend(principal.credential_digest_secret_refs)
        for client in self.oauth_clients.values():
            refs.append(client.client_secret_ref)
        for account in self.accounts.values():
            if account.owner not in self.owners or (account.enabled and not account.google_subject):
                raise ValueError("Invalid account identity")
            for binding in account.services.values():
                if binding.oauth_client not in self.oauth_clients:
                    raise ValueError("Invalid OAuth client reference")
                refs.append(binding.refresh_token_secret_ref)
        for context in self.contexts.values():
            for principal_id, grants in context.grants.items():
                if principal_id not in self.principals:
                    raise ValueError("Unknown grant principal")
                for account_id, grant in grants.items():
                    if set(grant.allow) - IMPLEMENTED:
                        raise ValueError("Unimplemented or unknown method in allow list")
                    if account_id not in self.accounts:
                        raise ValueError("Unknown grant account")
                    if self.principals[principal_id].owner != self.accounts[account_id].owner:
                        raise ValueError("Cross-owner grants are not supported")
                    if any("*" in m for m in grant.allow + grant.deny):
                        raise ValueError("Wildcard grants are not supported")
                    if any(r not in DOCS_REQUESTS for r in grant.constraints.allowed_docs_requests):
                        raise ValueError("Unsupported Docs operation")
        if any(not re.fullmatch(SECRET_PATTERN, ref) for ref in refs):
            raise ValueError("Invalid secret reference")
        return self


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node):
    mapping = {}
    for k, v in node.value:
        if k.value == "<<":
            raise ValueError("YAML merge keys are not supported")
        key = loader.construct_object(k)
        if not isinstance(key, str) or key == "<<" or key in mapping:
            raise ValueError("Duplicate, merge, or non-string YAML key")
        mapping[key] = loader.construct_object(v)
    return mapping


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def parse_policy(data: bytes) -> Policy:
    if len(data) > 1_000_000:
        raise ValueError("Policy exceeds size limit")
    if any(isinstance(token, AliasToken | AnchorToken | TagToken) for token in yaml.scan(data)):
        raise ValueError("YAML aliases, anchors, and tags are not supported")
    return Policy.model_validate(yaml.load(data, Loader=UniqueLoader))
