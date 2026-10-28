from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud.storage import Client

from .errors import AppError


@dataclass(frozen=True)
class Object:
    data: bytes
    generation: int


class ObjectStore(Protocol):
    def read(self, key: str) -> Object: ...
    def put(self, key: str, data: bytes, generation: int = 0) -> int: ...
    def delete(self, key: str, generation: int) -> None: ...


class GCSStore:
    def __init__(self, bucket: str, client: Client | None = None):
        self.bucket = (client or Client()).bucket(bucket)

    def read(self, key: str) -> Object:
        blob = self.bucket.blob(key)
        try:
            blob.reload()
            if blob.size and blob.size > 25_000_000:
                raise AppError("too_large", "Stored object exceeds size limit", 413)
            generation = int(blob.generation)
            return Object(blob.download_as_bytes(if_generation_match=generation), generation)
        except NotFound:
            raise AppError("not_found", "Object not found", 404) from None
        except PreconditionFailed:
            raise AppError("conflict", "Object changed; retry with a fresh read", 409) from None

    def put(self, key: str, data: bytes, generation: int = 0) -> int:
        blob = self.bucket.blob(key)
        try:
            blob.upload_from_string(data, if_generation_match=generation)
            return int(blob.generation)
        except PreconditionFailed:
            raise AppError("conflict", "Object changed; read and compare again", 409) from None

    def delete(self, key: str, generation: int) -> None:
        self.bucket.blob(key).delete(if_generation_match=generation)


class MemoryStore:
    """Deterministic adapter for tests, never selected by production configuration."""

    def __init__(self):
        self.objects: dict[str, Object] = {}
        self.lock = RLock()
        self.sequence = 0

    def read(self, key: str) -> Object:
        with self.lock:
            if key not in self.objects:
                raise AppError("not_found", "Object not found", 404)
            return self.objects[key]

    def put(self, key: str, data: bytes, generation: int = 0) -> int:
        with self.lock:
            current = self.objects.get(key)
            if (current.generation if current else 0) != generation:
                raise AppError("conflict", "Object changed", 409)
            self.sequence += 1
            self.objects[key] = Object(data, self.sequence)
            return self.sequence

    def delete(self, key: str, generation: int) -> None:
        with self.lock:
            if self.read(key).generation != generation:
                raise AppError("conflict", "Object changed", 409)
            del self.objects[key]
