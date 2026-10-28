"""An explicit allowlist of wrappers; Discovery describes inputs, never permission."""

import copy
import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from jsonschema import Draft7Validator

from .errors import AppError

CORE = {
    "gmail": {
        "users.getProfile",
        "users.messages.list",
        "users.messages.get",
        "users.threads.list",
        "users.threads.get",
        "users.threads.modify",
        "users.messages.modify",
        "users.messages.attachments.get",
        "users.labels.list",
        "users.labels.get",
        "users.labels.create",
        "users.labels.update",
        "users.labels.patch",
        "users.labels.delete",
        "users.drafts.list",
        "users.drafts.get",
        "users.drafts.create",
        "users.drafts.update",
    },
    "drive": {"files.list", "files.get", "files.create", "files.update"},
    "docs": {"documents.get", "documents.create", "documents.batchUpdate"},
}
VERSIONS = {"gmail": "v1", "drive": "v3", "docs": "v1"}


def discovery(api: str) -> dict[str, Any]:
    return json.loads(
        files("g_utils_mcp").joinpath(f"discovery/{api}.{VERSIONS[api]}.json").read_text()
    )


def catalog(api: str) -> dict[str, dict]:
    out = {}

    def walk(node):
        for method in node.get("methods", {}).values():
            out[method["id"]] = method
        for resource in node.get("resources", {}).values():
            walk(resource)

    walk(discovery(api))
    return out


def normalize(node: dict) -> dict:
    node = copy.deepcopy(node)
    if isinstance(node.get("required"), bool):
        node.pop("required")
    if "$ref" in node:
        return {"$ref": "#/definitions/" + node["$ref"]}
    if node.get("type") == "object":
        node.setdefault("properties", {})
        if "additionalProperties" not in node:
            node["additionalProperties"] = False
    for key in ("properties",):
        if key in node:
            node[key] = {k: normalize(v) for k, v in node[key].items()}
    if "items" in node:
        node["items"] = normalize(node["items"])
    if isinstance(node.get("additionalProperties"), dict):
        node["additionalProperties"] = normalize(node["additionalProperties"])
    # Discovery uses descriptive strings for numeric bounds and non-JSON-schema formats.
    for key in ("minimum", "maximum"):
        if key in node:
            node[key] = int(node[key])
    return node


@dataclass(frozen=True)
class Method:
    id: str
    name: str
    schema: dict


def build_registry() -> dict[str, Method]:
    registry = {}
    for api, paths in CORE.items():
        doc, methods = discovery(api), catalog(api)
        definitions = {k: normalize(v) for k, v in doc["schemas"].items()}
        for path in sorted(paths):
            method_id = api + "." + path
            method = methods[method_id]
            params = {k: normalize(v) for k, v in method.get("parameters", {}).items()}
            required = [k for k, v in method.get("parameters", {}).items() if v.get("required")]
            if "request" in method:
                params["body"] = normalize(method["request"])
                required.append("body")
            params["fields"] = {"type": "string", "maxLength": 1000}
            needed: dict[str, dict] = {}

            def collect(node, definitions=definitions, needed=needed):
                if isinstance(node, dict):
                    ref = node.get("$ref", "").removeprefix("#/definitions/")
                    if ref in definitions and ref not in needed:
                        needed[ref] = definitions[ref]
                        collect(definitions[ref])
                    for value in node.values():
                        collect(value)
                elif isinstance(node, list):
                    for value in node:
                        collect(value)

            collect(params)
            schema = {
                "type": "object",
                "properties": params,
                "required": required,
                "additionalProperties": False,
                "definitions": needed,
            }
            name = method_id.replace(".", "_")
            registry[name] = Method(method_id, name, schema)
    return registry


REGISTRY = build_registry()
IMPLEMENTED = {m.id for m in REGISTRY.values()} | {"drive.files.export"}


def validate_params(method: Method, params: dict) -> None:
    if next(Draft7Validator(method.schema).iter_errors(params), None):
        raise AppError("invalid_input", "Arguments do not match the method schema", 400)
    for key in ("maxResults", "pageSize"):
        if key in params and not 1 <= params[key] <= 100:
            raise AppError("invalid_input", "Page size must be between 1 and 100", 400)
