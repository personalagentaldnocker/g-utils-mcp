import hashlib
import hmac

from .credentials.secrets import Secrets
from .errors import AppError
from .policy.models import Policy


def authenticate(policy: Policy, secrets: Secrets, authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    alias, _, random_part = token.partition(".")
    principal = policy.principals.get(alias)
    if scheme.lower() != "bearer" or not principal or not principal.enabled or len(random_part) < 43:
        raise AppError("unauthenticated", "Authentication required", 401)
    digest = hashlib.sha256(token.encode()).hexdigest().encode()
    valid = False
    for ref in principal.credential_digest_secret_refs:
        valid |= hmac.compare_digest(digest, secrets.read(ref).strip())
    if not valid:
        raise AppError("unauthenticated", "Authentication required", 401)
    return alias
