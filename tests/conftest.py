import pytest

from g_utils_mcp.mcp_server import Caller
from g_utils_mcp.utils.auth import Policy

TOKEN = "t" * 43


class Call:
    """Fake Google request: attribute access builds the method path, execute() answers it."""

    def __init__(self, client, path, kwargs=None):
        self.client, self.path, self.kwargs = client, path, kwargs or {}

    def __getattr__(self, name):
        return lambda **kwargs: Call(self.client, self.path + [name], kwargs)

    def execute(self, num_retries=0):
        method_id = ".".join(self.path)
        self.client.calls.append((method_id, self.kwargs))
        answer = self.client.answers[method_id]
        return answer(self.kwargs) if callable(answer) else answer


class FakeClient:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def factory(self, api):
        return Call(self, [api])


@pytest.fixture
def policy_dict():
    return {
        "policy_revision": "test",
        "principals": {"agent": {"allowed_contexts": ["test"]}},
        "accounts": {
            "mail": {
                "enabled": True,
                "expected_email": "me@example.net",
                "services": ["gmail", "drive"],
            }
        },
        "contexts": {
            "test": {
                "grants": {
                    "agent": {
                        "mail": {
                            "allow": [
                                "gmail.users.messages.list",
                                "gmail.users.messages.get",
                                "gmail.users.messages.modify",
                                "gmail.users.messages.attachments.get",
                                "gmail.users.drafts.create",
                                "drive.files.get",
                                "drive.files.export",
                                "docs.documents.batchUpdate",
                            ],
                            "deny": ["gmail.users.messages.modify"],
                        }
                    }
                }
            }
        },
    }


@pytest.fixture
def policy(policy_dict):
    return Policy.model_validate(policy_dict)


@pytest.fixture
def secret():
    return {
        "oauth_client": {"client_id": "id", "client_secret": "s"},
        "principals": {"agent": {"token": TOKEN}},
        "accounts": {},
    }


@pytest.fixture
def who(policy, secret):
    return Caller("agent", policy, secret)
