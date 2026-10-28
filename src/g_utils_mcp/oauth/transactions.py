import json
import time

from ..errors import AppError
from ..storage import ObjectStore


class Transactions:
    def __init__(self, store: ObjectStore):
        self.store = store

    def create(self, state: str, data: dict) -> None:
        self.store.put("oauth/" + state, json.dumps({**data, "consumed": False}).encode())

    def consume(self, state: str) -> dict:
        obj = self.store.read("oauth/" + state)
        data = json.loads(obj.data)
        if data["consumed"] or data["expires"] <= time.time():
            raise AppError("invalid_enrollment", "Enrollment expired or already consumed", 400)
        self.store.put(
            "oauth/" + state, json.dumps({**data, "consumed": True}).encode(), obj.generation
        )
        return data
