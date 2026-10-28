import re
from typing import Protocol

from google.cloud import secretmanager

from ..errors import forbidden
from ..policy.models import SECRET_PATTERN


class Secrets(Protocol):
    def read(self, ref: str) -> bytes: ...
    def add(self, ref: str, payload: bytes) -> None: ...


class GCPSecrets:
    def __init__(self, projects: list[str]):
        self.projects = projects
        self.client = secretmanager.SecretManagerServiceClient()

    def validate(self, ref: str) -> str:
        match = re.fullmatch(SECRET_PATTERN, ref)
        if not match or match[1] not in self.projects:
            raise forbidden()
        return ref.rsplit("/versions/", 1)[0]

    def read(self, ref: str) -> bytes:
        self.validate(ref)
        return bytes(self.client.access_secret_version(name=ref).payload.data)

    def add(self, ref: str, payload: bytes) -> None:
        parent = self.validate(ref)
        self.client.add_secret_version(request={"parent": parent, "payload": {"data": payload}})
