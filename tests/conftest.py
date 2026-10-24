import hashlib

import pytest

from google_utils_mcp.policy.models import Policy

TOKEN = "agent." + "x" * 43
PREFIX = "projects/example/secrets/"


class FakeSecrets:
    def __init__(self):
        self.values = {PREFIX + "agent/versions/latest": hashlib.sha256(TOKEN.encode()).hexdigest().encode()}
        self.reads: list[str] = []

    def read(self, ref):
        self.reads.append(ref)
        return self.values[ref]

    def add(self, ref, payload):
        self.values[ref] = payload


@pytest.fixture
def policy_dict():
    return {
        "policy_revision": "test",
        "owners": {"owner": {"display_name": "Test"}},
        "principals": {"agent": {
            "owner": "owner", "credential_digest_secret_refs": [PREFIX + "agent/versions/latest"],
            "allowed_contexts": ["test"],
        }},
        "oauth_clients": {"web": {"client_id": "test.apps.googleusercontent.com",
                                  "client_secret_ref": PREFIX + "client/versions/latest"}},
        "accounts": {"mail": {
            "owner": "owner", "enabled": True, "expected_email": "test@example.net",
            "google_subject": "123", "services": {
                name: {"oauth_client": "web", "refresh_token_secret_ref": PREFIX + name + "/versions/latest",
                       "oauth_scopes": ["https://www.googleapis.com/auth/" + scope]}
                for name, scope in [("gmail", "gmail.modify"), ("drive", "drive")]
            },
        }},
        "contexts": {"test": {"grants": {"agent": {"mail": {
            "allow": ["gmail.users.messages.list", "drive.files.list", "docs.documents.get"],
        }}}}},
    }


@pytest.fixture
def policy(policy_dict):
    return Policy.model_validate(policy_dict)


@pytest.fixture
def secrets():
    return FakeSecrets()
