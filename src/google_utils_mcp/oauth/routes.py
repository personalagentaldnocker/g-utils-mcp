import json
import re
import secrets
import time

from google.auth.transport.requests import Request
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from starlette.responses import HTMLResponse, RedirectResponse

from ..errors import AppError
from .transactions import Transactions

SCOPES_IDENTITY = ["openid", "https://www.googleapis.com/auth/userinfo.email"]


class GoogleOAuthProvider:
    def __init__(self, secret_store, policies, base_url):
        self.secrets, self.policies, self.base_url = secret_store, policies, base_url

    def flow(self, transaction):
        policy = self.policies.current().policy
        client = policy.oauth_clients[transaction["oauth_client"]]
        config = {"web": {"client_id": client.client_id,
            "client_secret": self.secrets.read(client.client_secret_ref).decode(),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"}}
        return Flow.from_client_config(config, scopes=transaction["scopes"] + SCOPES_IDENTITY,
            state=transaction["state"], code_verifier=transaction["verifier"],
            redirect_uri=self.base_url + "/oauth/google/callback")

    def start(self, transaction):
        url, _ = self.flow(transaction).authorization_url(
            access_type="offline", prompt="consent", nonce=transaction["nonce"],
            login_hint=transaction["expected_email"])
        return url

    def exchange(self, code, transaction):
        flow = self.flow(transaction)
        flow.fetch_token(code=code)
        credentials = flow.credentials
        claims = id_token.verify_oauth2_token(credentials.id_token, Request(), credentials.client_id)
        scopes = credentials.granted_scopes or credentials.scopes or []
        return {"claims": claims, "refresh_token": credentials.refresh_token, "scopes": list(scopes)}


class Enrollment:
    def __init__(self, settings, policies, secrets_store, temporary, provider=None):
        self.policies, self.secrets, self.temporary = policies, secrets_store, temporary
        self.transactions = Transactions(temporary)
        self.provider = provider or GoogleOAuthProvider(secrets_store, policies, settings.public_base_url)

    def validate_intent(self, intent):
        if intent["expires"] <= time.time():
            raise AppError("invalid_enrollment", "Enrollment expired", 400)
        policy = self.policies.current().policy
        account = policy.accounts[intent["account"]]
        binding = account.services[intent["service"]]
        if (intent["expected_email"].lower() != account.expected_email.lower()
                or intent["oauth_client"] != binding.oauth_client
                or intent["target_secret"] != binding.refresh_token_secret_ref
                or set(intent["scopes"]) != set(binding.oauth_scopes)):
            raise AppError("invalid_enrollment", "Enrollment no longer matches policy", 400)
        return account

    def handle(self, path: str, params: dict):
        headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                   "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"}
        if path.endswith("/start"):
            intent_id = params.get("intent", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{43}", intent_id):
                raise AppError("invalid_enrollment", "Invalid enrollment", 400)
            # Intent exists only in the administratively writable policy bucket.
            intent = json.loads(self.policies.objects.read("enrollments/" + intent_id).data)
            self.validate_intent(intent)
            state = secrets.token_urlsafe(32)
            ledger_key = "enrollments/" + intent_id
            self.temporary.put(ledger_key, json.dumps({"status": "started", "expires": intent["expires"]}).encode())
            transaction = {**intent, "intent_id": intent_id, "state": state,
                           "nonce": secrets.token_urlsafe(32), "verifier": secrets.token_urlsafe(64)}
            self.transactions.create(state, transaction)
            return RedirectResponse(self.provider.start(transaction), headers=headers)
        state = params.get("state", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", state):
            raise AppError("invalid_enrollment", "Invalid OAuth state", 400)
        transaction = self.transactions.consume(state)
        account = self.validate_intent(transaction)
        if "error" in params or not params.get("code"):
            raise AppError("invalid_enrollment", "Google consent was not completed; start a new enrollment", 400)
        result = self.provider.exchange(params["code"], transaction)
        claims = result["claims"]
        if (claims.get("nonce") != transaction["nonce"] or not claims.get("email_verified")
                or claims.get("email", "").lower() != transaction["expected_email"].lower()
                or not claims.get("sub")
                or (account.google_subject and claims["sub"] != account.google_subject)
                or not set(transaction["scopes"]).issubset(result["scopes"])):
            raise AppError("invalid_enrollment", "Google identity or scopes did not match enrollment", 400)
        refresh_token = result.get("refresh_token")
        if not refresh_token:
            try:
                old = json.loads(self.secrets.read(transaction["target_secret"]))
                if (old.get("google_subject") == claims["sub"]
                        and old.get("account_alias") == transaction["account"]
                        and old.get("oauth_client") == transaction["oauth_client"]
                        and set(transaction["scopes"]).issubset(old.get("scopes", []))):
                    refresh_token = old["refresh_token"]
            except Exception:
                pass
        if not refresh_token:
            raise AppError("reauth_required", "Google did not issue a refresh token; repeat consent", 400)
        token = {"refresh_token": refresh_token, "google_subject": claims["sub"],
                 "account_alias": transaction["account"], "oauth_client": transaction["oauth_client"],
                 "scopes": result["scopes"], "connected_at": time.time()}
        self.secrets.add(transaction["target_secret"], json.dumps(token).encode())
        key = "enrollments/" + transaction["intent_id"]
        obj = self.temporary.read(key)
        self.temporary.put(key, json.dumps({"status": "connected_pending_activation",
            "google_subject": claims["sub"], "email": claims["email"], "scopes": result["scopes"],
            "expires": transaction["expires"]}).encode(), obj.generation)
        return HTMLResponse("Google account connected. Return to the operator CLI to review and activate it.", headers=headers)
