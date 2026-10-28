import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import PurePath

from .errors import AppError, forbidden
from .storage import ObjectStore


@dataclass(frozen=True)
class Origin:
    account: str
    method: str
    params: dict
    required_methods: tuple[str, ...] = ()


class Artifacts:
    def __init__(self, store: ObjectStore, limit: int = 20_000_000, ttl: int = 1800):
        self.store, self.limit, self.ttl = store, limit, ttl

    def create(
        self,
        principal: str,
        context: str,
        data: bytes,
        filename: str,
        mime_type: str = "application/octet-stream",
        origin: Origin | None = None,
    ) -> dict:
        if len(data) > self.limit:
            raise AppError("too_large", "File exceeds transfer limit", 413)
        filename = PurePath(filename.replace("\\", "/")).name
        filename = re.sub(r"[^\w. ()-]", "_", filename, flags=re.ASCII)[:180] or "file"
        if not re.fullmatch(r"[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+", mime_type):
            mime_type = "application/octet-stream"
        ref = secrets.token_urlsafe(32)
        metadata = {
            "file_ref": ref,
            "filename": filename,
            "mime_type": mime_type,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "principal": principal,
            "context": context,
            "expires": time.time() + self.ttl,
            "origin": vars(origin) if origin else None,
        }
        self.store.put("artifacts/" + ref + "/data", data)
        self.store.put("artifacts/" + ref + "/meta", json.dumps(metadata).encode())
        return self.public(metadata)

    @staticmethod
    def public(meta: dict) -> dict:
        return {
            k: meta[k] for k in ("file_ref", "filename", "mime_type", "size", "sha256", "expires")
        }

    def get(self, ref: str, principal: str, context: str) -> tuple[dict, bytes]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", ref):
            raise forbidden()
        meta = json.loads(self.store.read("artifacts/" + ref + "/meta").data)
        if (
            meta["principal"] != principal
            or meta["context"] != context
            or meta["expires"] <= time.time()
        ):
            raise forbidden()
        data = self.store.read("artifacts/" + ref + "/data").data
        if len(data) > self.limit or hashlib.sha256(data).hexdigest() != meta["sha256"]:
            raise AppError("unavailable", "Artifact integrity check failed", 503)
        return meta, data
