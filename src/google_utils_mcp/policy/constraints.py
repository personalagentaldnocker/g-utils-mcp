from ..errors import AppError, forbidden
from .models import Grant


def constrain(method: str, params: dict, grant: Grant) -> None:
    body = params.get("body", {})
    if method.startswith("gmail."):
        if params.get("userId", "me") != "me":
            raise forbidden()
        if method.endswith(".modify"):
            if set(body.get("addLabelIds", [])) & set(grant.constraints.forbidden_added_label_ids):
                raise forbidden()
        if method.startswith("gmail.users.labels.") and method.rsplit(".", 1)[1] in (
            "delete", "update", "patch"
        ) and not params.get("id", "").startswith("Label_"):
            raise AppError("invalid_input", "Only user labels may be edited or deleted", 400)
    if method in ("drive.files.create", "drive.files.update"):
        allowed = {"name", "description", "mimeType"}
        if method.endswith("create"):
            allowed.add("parents")
        if set(body) - allowed or "addParents" in params or "removeParents" in params:
            raise forbidden()
    if method == "docs.documents.create" and set(body) - {"title"}:
        raise forbidden()
    if method == "docs.documents.batchUpdate":
        requests = body.get("requests", [])
        if not requests or len(requests) > 100:
            raise AppError("invalid_input", "Provide between 1 and 100 edit requests", 400)
        if not body.get("writeControl", {}).get("requiredRevisionId"):
            raise AppError("invalid_input", "An expected document revision is required", 400)
        for request in requests:
            if len(request) != 1 or next(iter(request)) not in grant.constraints.allowed_docs_requests:
                raise forbidden()
