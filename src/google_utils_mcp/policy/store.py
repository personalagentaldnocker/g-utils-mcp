from dataclasses import dataclass

from ..errors import AppError
from ..storage import ObjectStore
from .models import Policy, parse_policy


@dataclass(frozen=True)
class Snapshot:
    policy: Policy
    generation: int


class PolicyStore:
    def __init__(self, objects: ObjectStore, key: str):
        self.objects, self.key = objects, key

    def current(self) -> Snapshot:
        try:
            obj = self.objects.read(self.key)
            return Snapshot(parse_policy(obj.data), obj.generation)
        except Exception:
            raise AppError("policy_unavailable", "Current policy is unavailable", 503) from None
