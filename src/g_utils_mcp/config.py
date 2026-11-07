"""Settings: two environment variables, everything else is a constant."""

import os

MAX_FILE_BYTES = 5_000_000  # files travel through the conversation as base64
MAX_RESULT_BYTES = 8_000_000  # fits one base64-encoded file plus metadata
SECRET_CACHE_SECONDS = 300  # revocation goes through the policy, which is checked every request
SCOPES = {
    "gmail": ["https://www.googleapis.com/auth/gmail.modify"],
    "drive": ["https://www.googleapis.com/auth/drive"],  # also covers the Docs methods
}
IDENTITY_SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]


def policy_uri() -> str:
    """gs://bucket/object of the policy file."""
    value = os.environ.get("POLICY_URI", "")
    if not value.startswith("gs://"):
        raise RuntimeError("Set POLICY_URI=gs://bucket/object")
    return value


def secret_name() -> str:
    """projects/PROJECT/secrets/NAME of the single secret."""
    value = os.environ.get("SECRET_NAME", "")
    if not value.startswith("projects/") or "/secrets/" not in value:
        raise RuntimeError("Set SECRET_NAME=projects/PROJECT/secrets/NAME")
    return value
