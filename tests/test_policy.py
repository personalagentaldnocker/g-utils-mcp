import json

import pytest

from google_utils_mcp.errors import AppError
from google_utils_mcp.identity import authenticate
from google_utils_mcp.policy.authorize import authorize
from google_utils_mcp.policy.models import parse_policy
from google_utils_mcp.policy.store import PolicyStore
from google_utils_mcp.storage import MemoryStore

from .conftest import TOKEN


@pytest.mark.parametrize("text", [
    "policy_revision: a\npolicy_revision: b", "a: &x [1]\nb: *x", "a: !python/x hi",
    "a: {<<: {x: 1}}", "policy_revision: test\nunknown: true",
])
def test_unsafe_yaml_is_rejected(text):
    with pytest.raises(ValueError):
        parse_policy(text.encode())


def test_deny_wins_and_disabled_account(policy):
    authorize(policy, "agent", "test", "mail", "gmail.users.messages.list")
    grant = policy.contexts["test"].grants["agent"]["mail"]
    grant.deny.append("gmail.users.messages.list")
    with pytest.raises(AppError):
        authorize(policy, "agent", "test", "mail", "gmail.users.messages.list")
    policy.accounts["mail"].enabled = False
    with pytest.raises(AppError):
        authorize(policy, "agent", "test", "mail", "drive.files.list")


@pytest.mark.parametrize("principal,context,account,method", [
    ("unknown", "test", "mail", "gmail.users.messages.list"),
    ("agent", "other", "mail", "gmail.users.messages.list"),
    ("agent", "test", "other", "gmail.users.messages.list"),
    ("agent", "test", "mail", "gmail.users.messages.send"),
])
def test_exact_grants(policy, principal, context, account, method):
    with pytest.raises(AppError):
        authorize(policy, principal, context, account, method)


def test_revocation_and_invalid_generation_are_observed(policy_dict):
    store = MemoryStore()
    g = store.put("policy", json.dumps(policy_dict).encode())
    reader = PolicyStore(store, "policy")
    assert reader.current().generation == g
    policy_dict["accounts"]["mail"]["enabled"] = False
    g2 = store.put("policy", json.dumps(policy_dict).encode(), g)
    assert not reader.current().policy.accounts["mail"].enabled
    store.put("policy", b"invalid", g2)
    with pytest.raises(AppError, match="unavailable"):
        reader.current()
    with pytest.raises(AppError, match="changed"):
        store.put("policy", b"stale", g)


def test_authentication_rotation_and_revocation(policy, secrets):
    assert authenticate(policy, secrets, "Bearer " + TOKEN) == "agent"
    with pytest.raises(AppError):
        authenticate(policy, secrets, "Bearer " + TOKEN + "wrong")
    policy.principals["agent"].enabled = False
    with pytest.raises(AppError):
        authenticate(policy, secrets, "Bearer " + TOKEN)
