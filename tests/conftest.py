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


class Blob:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self.metadata, self.content_type, self.size, self.generation = None, None, None, 1

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        import datetime

        self.store[self.name] = (
            data,
            self.metadata,
            content_type,
            datetime.datetime.now(datetime.UTC),
        )

    def reload(self):
        from google.api_core.exceptions import NotFound

        if self.name not in self.store:
            raise NotFound("missing")
        data, self.metadata, self.content_type, self.time_created = self.store[self.name]
        self.size = len(data)

    def download_as_bytes(self, if_generation_match=None):
        return self.store[self.name][0]


class Bucket:
    def __init__(self):
        self.store = {}

    def blob(self, name):
        return Blob(self.store, name)


@pytest.fixture
def bucket(monkeypatch):
    """In-memory temporary bucket behind helpers.file_store / file_load."""
    from g_utils_mcp.utils import helpers

    fake = Bucket()
    monkeypatch.setenv("TEMP_BUCKET", "temp")
    monkeypatch.setattr(helpers, "_bucket", lambda name: fake)
    return fake
