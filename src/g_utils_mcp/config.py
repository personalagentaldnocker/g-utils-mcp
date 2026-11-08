"""Settings: three environment variables, everything else is a constant."""

import os

INLINE_FILE_BYTES = 5_000_000  # up to this size, files travel in the conversation as base64
MAX_FILE_BYTES = 25_000_000  # larger files go through the temporary bucket (Gmail's limit)
FILE_REF_SECONDS = 3600  # a file_ref works for one hour; the bucket deletes after a day
MAX_RESULT_BYTES = 8_000_000  # fits one inline file plus metadata
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


def temp_bucket() -> str:
    """Bucket for files above INLINE_FILE_BYTES (file contents only, never credentials)."""
    value = os.environ.get("TEMP_BUCKET", "")
    if not value:
        raise RuntimeError("Set TEMP_BUCKET to the temporary bucket name")
    return value
