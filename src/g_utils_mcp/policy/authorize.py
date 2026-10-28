from ..errors import forbidden
from .models import Grant, Policy, ServiceBinding


def authorize(
    policy: Policy, principal_id: str, context: str, account: str, method: str
) -> tuple[Grant, ServiceBinding]:
    principal = policy.principals.get(principal_id)
    target = policy.accounts.get(account)
    ctx = policy.contexts.get(context)
    if not principal or not principal.enabled or not target or not target.enabled or not ctx:
        raise forbidden()
    if context not in principal.allowed_contexts or principal.owner != target.owner:
        raise forbidden()
    grant = ctx.grants.get(principal_id, {}).get(account)
    service = "drive" if method.startswith("docs.") else method.split(".")[0]
    binding = target.services.get("gmail" if service == "gmail" else "drive")
    if not grant or not binding or method not in grant.allow or method in grant.deny:
        raise forbidden()
    return grant, binding
