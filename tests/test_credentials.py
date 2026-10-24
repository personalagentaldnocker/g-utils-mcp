import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from google_utils_mcp.credentials.google_oauth import GoogleClients
from google_utils_mcp.errors import AppError


def test_refresh_coordination_binding_isolation_and_rotation(policy, secrets, monkeypatch):
    from google_utils_mcp.credentials import google_oauth

    client_ref = policy.oauth_clients["web"].client_secret_ref
    binding = policy.accounts["mail"].services["gmail"]
    secrets.values[client_ref] = b"test-client-secret"
    token = {
        "refresh_token": "test-refresh",
        "account_alias": "mail",
        "google_subject": "123",
        "oauth_client": "web",
        "scopes": binding.oauth_scopes,
    }
    secrets.values[binding.refresh_token_secret_ref] = json.dumps(token).encode()
    refreshes = []

    def refresh(credentials, request):
        refreshes.append(credentials.refresh_token)
        credentials.token = "test-access"
        credentials.expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

    monkeypatch.setattr(google_oauth.Credentials, "refresh", refresh)
    monkeypatch.setattr(google_oauth, "build_from_document", lambda doc, credentials: credentials)
    clients = GoogleClients(secrets)
    with ThreadPoolExecutor(max_workers=4) as pool:
        credentials = list(
            pool.map(lambda _: clients.build(policy, "mail", binding, "gmail"), range(4))
        )
    assert len(refreshes) == 1
    assert len({id(c) for c in credentials}) == 4
    token["refresh_token"] = "rotated-refresh"
    secrets.values[binding.refresh_token_secret_ref] = json.dumps(token).encode()
    clients.build(policy, "mail", binding, "gmail")
    assert len(refreshes) == 2
    token["google_subject"] = "foreign-subject"
    secrets.values[binding.refresh_token_secret_ref] = json.dumps(token).encode()
    with pytest.raises(AppError):
        clients.build(policy, "mail", binding, "gmail")
    assert len(refreshes) == 2
