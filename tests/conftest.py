import hashlib
import json

import pytest

from g_utils_mcp import utils
from g_utils_mcp.policy import Caller

TOKEN = "agent." + "x" * 43
SECRET = "projects/example/secrets/mail/versions/latest"


def make_policy() -> dict:
    return {
        "version": 2,
        "principals": {"agent": {"token_sha256": [hashlib.sha256(TOKEN.encode()).hexdigest()]}},
        "accounts": {"mail": {"email": "test@example.net", "secret": SECRET}},
        "grants": {
            "agent": {
                "mail": {
                    "allow": [
                        "gmail_users_messages_list",
                        "drive_files_list",
                        "docs_documents_get",
                    ],
                    "deny": ["gmail_users_messages_send"],
                }
            }
        },
    }


@pytest.fixture
def policy() -> dict:
    return make_policy()


@pytest.fixture
def caller(policy) -> Caller:
    return Caller("agent", policy, 1)


def allow(caller: Caller, *tools: str) -> None:
    caller.policy["grants"]["agent"]["mail"]["allow"].extend(tools)


class FakeNode:
    """Records `service.users().messages().list(**kw).execute()` style calls."""

    def __init__(self, google, path=()):
        self.google, self.path = google, path

    def __getattr__(self, name):
        def method(**kwargs):
            node = FakeNode(self.google, self.path + (name,))
            if kwargs:
                self.google.calls.append((node.path, kwargs))
            return node

        return method

    def execute(self, **kwargs):
        if not self.google.calls or self.google.calls[-1][0] != self.path:
            self.google.calls.append((self.path, {}))
        result = self.google.results.get(self.path[-1], self.google.result)
        return result(self.google.calls[-1][1]) if callable(result) else result

    def close(self):
        pass


class FakeGoogle:
    def __init__(self):
        self.calls: list = []
        self.credential_loads: list[str] = []
        self.result: object = {"messages": [{"id": "one"}]}
        self.results: dict = {}
        self.downloads: dict[str, bytes] = {}


class FakeBlob:
    def __init__(self, bucket, name, data=b"", generation=0):
        self.bucket, self.name, self.data, self.generation = bucket, name, data, generation
        self.metadata: dict | None = None
        self.reloads = self.downloads = 0

    @property
    def size(self):
        return len(self.data)

    def reload(self):
        self.reloads += 1
        if self.generation == 0:
            raise FileNotFoundError(self.name)

    def download_as_bytes(self, if_generation_match=None):
        assert if_generation_match in (None, self.generation)
        self.downloads += 1
        return self.data

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        assert if_generation_match in (None, self.generation)
        self.data = data if isinstance(data, bytes) else data.encode()
        self.bucket.sequence += 1
        self.generation = self.bucket.sequence
        self.bucket.objects[self.name] = self


class FakeBucket:
    def __init__(self):
        self.objects: dict[str, FakeBlob] = {}
        self.sequence = 0

    def blob(self, name):
        return self.objects.get(name) or FakeBlob(self, name)

    def get_blob(self, name):
        return self.objects.get(name)


@pytest.fixture
def google(monkeypatch) -> FakeGoogle:
    fake = FakeGoogle()

    def credentials(account, secret):
        fake.credential_loads.append(account)
        return object()

    monkeypatch.setattr(utils, "credentials", credentials)
    monkeypatch.setattr(utils, "service", lambda api, creds: FakeNode(fake, (api,)))
    monkeypatch.setattr(utils, "_download", lambda request: fake.downloads[request.path[-1]])
    return fake


@pytest.fixture
def files(monkeypatch) -> FakeBucket:
    bucket = FakeBucket()
    monkeypatch.setattr(utils, "temp_bucket", lambda: bucket)
    return bucket


def policy_blob(policy: dict) -> FakeBlob:
    blob = FakeBucket().blob("policy.yml")
    blob.upload_from_string(json.dumps(policy).encode())
    return blob
