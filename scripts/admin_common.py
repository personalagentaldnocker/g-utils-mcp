import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from g_utils.config import Settings
from g_utils.credentials.secrets import GCPSecrets
from g_utils.policy.models import parse_policy
from g_utils.policy.store import PolicyStore
from g_utils.registry import IMPLEMENTED, VERSIONS, catalog
from g_utils.storage import GCSStore


def protected_write(path: Path, data: bytes, *, replace: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if replace else os.O_EXCL)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)


def load_policy(path: Path):
    policy = parse_policy(path.read_bytes())
    validate_capabilities(policy)
    return policy


def validate_capabilities(policy):
    known = set().union(*(catalog(api) for api in VERSIONS))
    for ctx in policy.contexts.values():
        for grants in ctx.grants.values():
            for grant in grants.values():
                if set(grant.allow) - IMPLEMENTED:
                    raise ValueError("Policy allows methods without implemented wrappers")
                if set(grant.deny) - known:
                    raise ValueError("Policy denies unknown methods")


def save_policy(path: Path, policy):
    # Validate references after each local edit, never publish implicitly.
    from g_utils.policy.models import Policy

    value = Policy.model_validate(policy.model_dump())
    validate_capabilities(value)
    protected_write(
        path, yaml.safe_dump(value.model_dump(), sort_keys=False).encode(), replace=True
    )


def cloud():
    settings = Settings()
    settings.require_cloud()
    uri = urlsplit(settings.policy_uri)
    store = PolicyStore(GCSStore(uri.netloc), uri.path.lstrip("/"))
    return settings, store, GCPSecrets(settings.allowed_secret_projects)


def generation_file(path: Path) -> Path:
    return Path(str(path) + ".generation")


def report(value):
    print(json.dumps(value, indent=2))
