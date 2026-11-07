import pytest

from g_utils_mcp.utils.auth import authenticate, authorize, constrain, parse_policy
from g_utils_mcp.utils.helpers import AppError

from .conftest import TOKEN


def test_parse_yaml_and_reject_unsafe_yaml():
    assert parse_policy(b"policy_revision: x\n").principals == {}
    for bad in (b"a: &x 1\nb: *x\n", b"policy_revision: x\npolicy_revision: y\n"):
        with pytest.raises(ValueError):
            parse_policy(bad)


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["contexts"]["test"]["grants"]["agent"]["mail"]["allow"].append("gmail.*"),
        lambda p: p["contexts"]["test"]["grants"]["agent"]["mail"]["allow"].append(
            "gmail.users.messages.send"
        ),
        lambda p: p["contexts"]["test"]["grants"].update(ghost={}),
        lambda p: p["principals"]["agent"].update(allowed_contexts=["nowhere"]),
        lambda p: p["accounts"]["mail"].update(services=["calendar"]),
        lambda p: p.update(extra=1),
    ],
)
def test_invalid_policies_are_rejected(policy_dict, change):
    from g_utils_mcp.utils.auth import Policy

    change(policy_dict)
    with pytest.raises(ValueError):
        Policy.model_validate(policy_dict)


def test_authorize_allows_granted_method(policy):
    assert authorize(policy, "agent", "test", "mail", "gmail.users.messages.list")


@pytest.mark.parametrize(
    "principal,context,account,method",
    [
        ("agent", "test", "mail", "gmail.users.messages.modify"),  # denied wins over allow
        ("agent", "test", "mail", "gmail.users.labels.list"),  # not granted
        ("agent", "other", "mail", "gmail.users.messages.list"),  # unknown context
        ("agent", "test", "nobody", "gmail.users.messages.list"),  # unknown account
        ("ghost", "test", "mail", "gmail.users.messages.list"),  # unknown principal
    ],
)
def test_authorize_denies(policy, principal, context, account, method):
    with pytest.raises(AppError):
        authorize(policy, principal, context, account, method)


def test_disabled_account_and_missing_service_are_denied(policy_dict):
    from g_utils_mcp.utils.auth import Policy

    policy_dict["accounts"]["mail"]["services"] = ["drive"]
    with pytest.raises(AppError):
        authorize(
            Policy.model_validate(policy_dict), "agent", "test", "mail", "gmail.users.messages.list"
        )
    policy_dict["accounts"]["mail"].update(services=["gmail"], enabled=False)
    with pytest.raises(AppError):
        authorize(
            Policy.model_validate(policy_dict), "agent", "test", "mail", "gmail.users.messages.list"
        )


def test_constraints(policy):
    grant = authorize(policy, "agent", "test", "mail", "gmail.users.messages.list")
    with pytest.raises(AppError):
        constrain("gmail.users.messages.list", {"userId": "other@example.net"}, grant)
    with pytest.raises(AppError):
        constrain("gmail.users.messages.modify", {"body": {"addLabelIds": ["TRASH"]}}, grant)
    with pytest.raises(AppError):
        constrain("gmail.users.labels.delete", {"id": "INBOX"}, grant)
    with pytest.raises(AppError):
        constrain("drive.files.update", {"body": {"parents": ["x"]}}, grant)
    with pytest.raises(AppError):  # Docs edits need an expected revision
        constrain("docs.documents.batchUpdate", {"body": {"requests": [{"insertText": {}}]}}, grant)
    constrain(
        "docs.documents.batchUpdate",
        {"body": {"requests": [{"insertText": {}}], "writeControl": {"requiredRevisionId": "r"}}},
        grant,
    )


def test_authenticate(policy, secret):
    assert authenticate("Bearer " + TOKEN, policy, secret) == "agent"
    for header in ("", "Bearer wrong" + TOKEN, "Basic " + TOKEN, "Bearer "):
        with pytest.raises(AppError):
            authenticate(header, policy, secret)
    policy.principals["agent"].enabled = False
    with pytest.raises(AppError):
        authenticate("Bearer " + TOKEN, policy, secret)


def test_policy_is_downloaded_only_when_generation_changes(monkeypatch):
    from g_utils_mcp.utils import auth

    state = {"generation": 1, "downloads": 0}

    def read(uri):
        state["downloads"] += 1
        return f"policy_revision: r{state['generation']}".encode(), state["generation"]

    monkeypatch.setattr(auth, "gcs_generation", lambda uri: state["generation"])
    monkeypatch.setattr(auth, "gcs_read", read)
    monkeypatch.setitem(auth._policy, "generation", None)
    assert auth.current_policy("gs://b/p").policy_revision == "r1"
    assert auth.current_policy("gs://b/p").policy_revision == "r1"
    assert state["downloads"] == 1
    state["generation"] = 2
    assert auth.current_policy("gs://b/p").policy_revision == "r2"
    assert state["downloads"] == 2
