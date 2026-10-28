import hashlib
import json
from datetime import UTC, datetime, timedelta
from threading import RLock

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build_from_document

from ..errors import AppError, forbidden
from ..policy.models import Policy, ServiceBinding
from ..registry import discovery
from .secrets import Secrets


class GoogleClients:
    def __init__(self, secrets: Secrets):
        self.secrets = secrets
        self.lock = RLock()
        self.cache: dict[tuple, tuple] = {}

    def build(self, policy: Policy, account: str, binding: ServiceBinding, api: str):
        target = policy.accounts[account]
        client = policy.oauth_clients[binding.oauth_client]
        raw_token = self.secrets.read(binding.refresh_token_secret_ref)
        token = json.loads(raw_token)
        if (
            token.get("account_alias") != account
            or token.get("google_subject") != target.google_subject
            or token.get("oauth_client") != binding.oauth_client
            or not set(binding.oauth_scopes).issubset(token.get("scopes", []))
        ):
            raise forbidden()
        client_secret = self.secrets.read(client.client_secret_ref).decode()
        key = (
            account,
            target.google_subject,
            client.client_id,
            binding.refresh_token_secret_ref,
            tuple(binding.oauth_scopes),
            hashlib.sha256(raw_token).digest(),
            hashlib.sha256(client_secret.encode()).digest(),
        )
        credentials = Credentials(
            token=None,
            refresh_token=token["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client.client_id,
            client_secret=client_secret,
            scopes=binding.oauth_scopes,
        )
        with self.lock:
            cached = self.cache.get(key)
            if (
                cached
                and cached[1]
                and cached[1] > datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=2)
            ):
                credentials.token, credentials.expiry = cached
            else:
                try:
                    credentials.refresh(Request())
                except RefreshError as exc:
                    invalid = any(
                        isinstance(arg, dict) and arg.get("error") == "invalid_grant"
                        for arg in exc.args
                    )
                    raise AppError(
                        "reauth_required" if invalid else "upstream_failure",
                        "Google refresh failed; reconnect for invalid grants",
                        401 if invalid else 503,
                    ) from None
                if len(self.cache) >= 64:
                    self.cache.clear()
                self.cache[key] = (credentials.token, credentials.expiry)
                if credentials.refresh_token != token["refresh_token"]:
                    token["refresh_token"] = credentials.refresh_token
                    self.secrets.add(binding.refresh_token_secret_ref, json.dumps(token).encode())
        # Every request gets a new API/HTTP client. Only short-lived access tokens are shared.
        return build_from_document(json.dumps(discovery(api)), credentials=credentials)
