import json
from pathlib import Path

import pytest

from g_utils_mcp import policy as pol
from g_utils_mcp.app import KNOWN
from g_utils_mcp.policy import Caller
from g_utils_mcp.utils import AppError

from .conftest import TOKEN, make_policy, policy_blob


def parse(policy: dict) -> dict:
    return pol.parse(json.dumps(policy).encode(), KNOWN)


@pytest.mark.parametrize(
    "text",
    [
        "version: 2\nversion: 2",
        "a: &x [1]\nb: *x",
        "a: !python/x hi",
        "a: {<<: {x: 1}}",
        "version: 2\nprincipals: {}\naccounts: {}\ngrants: {}\nunknown: true",
        "version: 1\nprincipals: {}\naccounts: {}\ngrants: {}",
    ],
)
def test_unsafe_or_unknown_yaml_is_rejected(text):
    with pytest.raises(ValueError):
        pol.parse(text.encode(), KNOWN)


@pytest.mark.parametrize("name", ["policy.example.yml", "policy.deny-all.yml"])
def test_examples_are_valid(name):
    pol.parse((Path("examples") / name).read_bytes(), KNOWN)


def test_allow_must_name_implemented_tools_but_deny_may_name_anything(policy):
    policy["grants"]["agent"]["mail"]["deny"].append("gmail_users_messages_delete")
    parse(policy)
    policy["grants"]["agent"]["mail"]["allow"].append("gmail_users_messages_send")
    with pytest.raises(ValueError, match="Unknown or unimplemented"):
        parse(policy)


@pytest.mark.parametrize("section,name", [("principals", "agent"), ("accounts", "mail")])
def test_grants_must_reference_known_names(policy, section, name):
    del policy[section][name]
    with pytest.raises(ValueError):
        parse(policy)


def test_bad_secret_reference_and_digest_rejected(policy):
    policy["accounts"]["mail"]["secret"] = "projects/x/secrets/y"
    with pytest.raises(ValueError):
        parse(policy)
    policy = make_policy()
    policy["principals"]["agent"]["token_sha256"] = ["not-hex"]
    with pytest.raises(ValueError):
        parse(policy)


def test_check_is_exact_and_deny_wins(caller):
    pol.check(caller, "mail", "gmail_users_messages_list")
    for account, tool in [
        ("mail", "gmail_users_messages_send"),
        ("mail", "gmail_users_labels_delete"),
        ("other", "gmail_users_messages_list"),
    ]:
        with pytest.raises(AppError):
            pol.check(caller, account, tool)
    with pytest.raises(AppError):
        pol.check(Caller("someone", caller.policy, 1), "mail", "gmail_users_messages_list")
    caller.policy["grants"]["agent"]["mail"]["deny"].append("gmail_users_messages_list")
    with pytest.raises(AppError):
        pol.check(caller, "mail", "gmail_users_messages_list")
    assert "gmail_users_messages_list" not in pol.tools_for(caller)["mail"]


def test_authentication_and_rotation(policy):
    assert pol.authenticate(policy, "Bearer " + TOKEN) == "agent"
    for header in ["Bearer " + TOKEN + "x", "Basic " + TOKEN, "", "Bearer agent.short"]:
        with pytest.raises(AppError):
            pol.authenticate(policy, header)
    other = "agent." + "y" * 43
    policy["principals"]["agent"]["token_sha256"].append(
        __import__("hashlib").sha256(other.encode()).hexdigest()
    )
    assert pol.authenticate(policy, "Bearer " + other) == "agent"


def test_loader_downloads_only_when_generation_changes(policy):
    blob = policy_blob(policy)
    current = pol.loader(blob, KNOWN)
    first = current()
    current()
    assert blob.reloads == 2 and blob.downloads == 1
    # Revocation: the next request sees the new generation.
    del policy["grants"]["agent"]
    blob.upload_from_string(json.dumps(policy).encode())
    revoked, generation = current()
    assert generation > first[1] and revoked["grants"] == {} and blob.downloads == 2
    # An invalid new generation fails closed instead of serving the old policy.
    blob.upload_from_string(b"not: [valid")
    with pytest.raises(AppError, match="unavailable"):
        current()


@pytest.mark.parametrize(
    "method,params",
    [
        ("gmail.users.messages.list", {"userId": "me", "maxResults": 101}),
        ("gmail.users.messages.list", {"userId": "me", "access_token": "x"}),
        (
            "gmail.users.threads.modify",
            {"userId": "me", "id": "t", "body": {"addLabelIds": ["TRASH"]}},
        ),
        ("gmail.users.labels.delete", {"userId": "me", "id": "INBOX"}),
        ("drive.files.update", {"fileId": "f", "body": {"trashed": True}}),
        ("drive.files.update", {"fileId": "f", "body": {}, "addParents": "p"}),
        ("docs.documents.create", {"body": {"title": "t", "body": {}}}),
        (
            "docs.documents.batchUpdate",
            {"documentId": "d", "body": {"requests": [{"insertText": {"text": "a"}}]}},
        ),
        (
            "docs.documents.batchUpdate",
            {
                "documentId": "d",
                "body": {
                    "writeControl": {"requiredRevisionId": "r"},
                    "requests": [{"deleteNamedRange": {"name": "x"}}],
                },
            },
        ),
    ],
)
def test_argument_rules(method, params):
    with pytest.raises(AppError):
        pol.check_args(method, params)


def test_valid_docs_edit_passes():
    pol.check_args(
        "docs.documents.batchUpdate",
        {
            "documentId": "d",
            "body": {
                "writeControl": {"requiredRevisionId": "r1"},
                "requests": [{"insertText": {"text": "x", "location": {"index": 1}}}],
            },
        },
    )
