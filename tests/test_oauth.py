import json
import secrets as random
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from google_utils_mcp.config import Settings
from google_utils_mcp.errors import AppError
from google_utils_mcp.oauth.routes import Enrollment
from google_utils_mcp.oauth.transactions import Transactions
from google_utils_mcp.policy.store import PolicyStore
from google_utils_mcp.storage import MemoryStore


class Provider:
    def __init__(self):
        self.transaction = None
        self.calls = 0
        self.wrong_email = False

    def start(self, transaction):
        self.transaction = transaction
        return "https://accounts.google.com/authorize"

    def exchange(self, code, transaction):
        self.calls += 1
        return {
            "claims": {
                "nonce": transaction["nonce"],
                "email_verified": True,
                "sub": "123",
                "email": "wrong@example.net" if self.wrong_email else "test@example.net",
            },
            "scopes": transaction["scopes"],
            "refresh_token": "test-only-not-a-real-token",
        }


def test_enrollment_cross_instance_replay_and_no_policy_write(policy_dict, secrets):
    policy_dict["accounts"]["mail"]["enabled"] = False
    store, temp = MemoryStore(), MemoryStore()
    gen = store.put("policy", json.dumps(policy_dict).encode())
    policy = PolicyStore(store, "policy")
    provider = Provider()
    instance = Enrollment(Settings(), policy, secrets, temp, provider)
    intent_id = random.token_urlsafe(32)
    binding = policy.current().policy.accounts["mail"].services["gmail"]
    intent = {
        "account": "mail",
        "service": "gmail",
        "expected_email": "test@example.net",
        "oauth_client": "web",
        "target_secret": binding.refresh_token_secret_ref,
        "scopes": binding.oauth_scopes,
        "expires": time.time() + 600,
    }
    store.put("enrollments/" + intent_id, json.dumps(intent).encode())
    assert instance.handle("/start", {"intent": intent_id}).status_code == 307
    other = Enrollment(Settings(), policy, secrets, temp, provider)
    with pytest.raises(AppError):
        other.handle("/start", {"intent": intent_id})
    state = provider.transaction["state"]
    assert other.handle("/callback", {"state": state, "code": "code"}).status_code == 200
    assert json.loads(secrets.values[binding.refresh_token_secret_ref])["google_subject"] == "123"
    assert policy.current().generation == gen
    assert not policy.current().policy.accounts["mail"].enabled
    with pytest.raises(AppError):
        instance.handle("/callback", {"state": state, "code": "code"})
    assert provider.calls == 1


def test_transaction_consumption_is_atomic():
    store = MemoryStore()
    tx = Transactions(store)
    tx.create("state", {"expires": time.time() + 10})

    def consume():
        try:
            tx.consume("state")
            return True
        except AppError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: consume(), range(2))) == 1


def test_expired_transaction():
    tx = Transactions(MemoryStore())
    tx.create("state", {"expires": time.time() - 1})
    with pytest.raises(AppError):
        tx.consume("state")


def test_google_authorization_url_has_pkce_nonce_and_exact_callback(policy_dict, secrets):
    from urllib.parse import parse_qs, urlsplit

    from google_utils_mcp.oauth.routes import GoogleOAuthProvider

    store = MemoryStore()
    store.put("policy", json.dumps(policy_dict).encode())
    policies = PolicyStore(store, "policy")
    ref = policies.current().policy.oauth_clients["web"].client_secret_ref
    secrets.values[ref] = b"test-client-secret"
    provider = GoogleOAuthProvider(secrets, policies, "https://service.example.net")
    url = provider.start(
        {
            "oauth_client": "web",
            "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
            "state": "state",
            "nonce": "nonce",
            "verifier": "x" * 64,
            "expected_email": "test@example.net",
        }
    )
    query = parse_qs(urlsplit(url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["nonce"] == ["nonce"]
    assert query["redirect_uri"] == ["https://service.example.net/oauth/google/callback"]


@pytest.mark.parametrize("mismatch", ["email", "nonce", "sub", "email_verified", "scopes"])
def test_callback_rejects_wrong_identity_and_scopes(policy_dict, secrets, mismatch):
    store, temp = MemoryStore(), MemoryStore()
    store.put("policy", json.dumps(policy_dict).encode())
    policies = PolicyStore(store, "policy")
    provider = Provider()
    enrollment = Enrollment(Settings(), policies, secrets, temp, provider)
    intent_id = random.token_urlsafe(32)
    binding = policies.current().policy.accounts["mail"].services["gmail"]
    intent = {
        "account": "mail",
        "service": "gmail",
        "expected_email": "test@example.net",
        "oauth_client": "web",
        "target_secret": binding.refresh_token_secret_ref,
        "scopes": binding.oauth_scopes,
        "expires": time.time() + 600,
    }
    store.put("enrollments/" + intent_id, json.dumps(intent).encode())
    enrollment.handle("/start", {"intent": intent_id})
    transaction = provider.transaction
    result = provider.exchange("code", transaction)
    if mismatch == "scopes":
        result["scopes"] = []
    else:
        result["claims"][mismatch] = False if mismatch == "email_verified" else "wrong"
    provider.exchange = lambda code, tx: result
    with pytest.raises(AppError):
        enrollment.handle("/callback", {"state": transaction["state"], "code": "code"})
    assert binding.refresh_token_secret_ref not in secrets.values
