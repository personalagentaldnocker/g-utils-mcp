import json

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

    def build(self, policy: Policy, account: str, binding: ServiceBinding, api: str):
        target = policy.accounts[account]
        client = policy.oauth_clients[binding.oauth_client]
        token = json.loads(self.secrets.read(binding.refresh_token_secret_ref))
        if (
            token.get("account_alias") != account
            or token.get("google_subject") != target.google_subject
            or token.get("oauth_client") != binding.oauth_client
            or not set(binding.oauth_scopes).issubset(token.get("scopes", []))
        ):
            raise forbidden()
        credentials = Credentials(
            token=None,
            refresh_token=token["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client.client_id,
            client_secret=self.secrets.read(client.client_secret_ref).decode(),
            scopes=binding.oauth_scopes,
        )
        try:
            credentials.refresh(Request())
        except RefreshError:
            raise AppError("reauth_required", "Google account requires reconnection", 401) from None
        # No global account clients or cross-request refresh-token cache.
        return build_from_document(json.dumps(discovery(api)), credentials=credentials)
