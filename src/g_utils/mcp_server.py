from contextvars import ContextVar
from typing import Any

import anyio
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool

from .errors import AppError
from .gateway import Caller, Gateway
from .policy.authorize import authorize
from .registry import REGISTRY

caller_context: ContextVar[Caller] = ContextVar("caller")

COMPOSE = {
    "draft_id": {"type": "string"},
    "expected_revision": {"type": "string"},
    "to": {"type": "array", "items": {"type": "string"}},
    "cc": {"type": "array", "items": {"type": "string"}},
    "subject": {"type": "string"},
    "text": {"type": "string"},
    "html": {"type": "string"},
    "reply_to_message_id": {"type": "string"},
    "reply_all": {"type": "boolean"},
    "add_file_refs": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
    "remove_attachment_refs": {"type": "array", "maxItems": 100, "items": {"type": "string"}},
}
HELPERS: dict[str, tuple[str, dict, list[str], list[str]]] = {
    "gmail_attachment_download": (
        "Download a MIME part (inline or external attachment) from a message to an artifact.",
        {"message_id": {"type": "string"}, "part_id": {"type": "string"}},
        ["message_id", "part_id"],
        ["gmail.users.messages.get"],
    ),
    "gmail_draft_compose": (
        "Create/edit an unsent draft, preserving other MIME parts. Read the draft revision before editing.",
        COMPOSE,
        [],
        ["gmail.users.drafts.create", "gmail.users.drafts.update"],
    ),
    "drive_upload": (
        "Upload artifact bytes to a new or existing Drive file.",
        {
            "file_ref": {"type": "string"},
            "file_id": {"type": "string"},
            "metadata": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "mimeType": {"type": "string"},
                    "parents": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
        },
        ["file_ref"],
        ["drive.files.create", "drive.files.update"],
    ),
    "drive_download": (
        "Download binary content or export a Google Doc to an artifact.",
        {"file_id": {"type": "string"}, "export_mime_type": {"type": "string"}},
        ["file_id"],
        ["drive.files.get"],
    ),
}


def permitted(caller: Caller, methods: list[str]) -> bool:
    for context in caller.policy.contexts:
        for account in caller.policy.accounts:
            for method in methods:
                try:
                    authorize(caller.policy, caller.principal, context, account, method)
                    return True
                except AppError:
                    pass
    return False


def tools(caller: Caller) -> list[Tool]:
    result = []
    base = {"context": {"type": "string"}, "account": {"type": "string"}}
    for name, method in REGISTRY.items():
        if not permitted(caller, [method.id]):
            continue
        params = {k: v for k, v in method.schema.items() if k != "definitions"}
        schema = {
            "type": "object",
            "properties": {
                **base,
                "params": params,
                "expected_revision": {"type": "string"},
                "filename": {"type": "string"},
            },
            "required": ["context", "account", "params"],
            "additionalProperties": False,
            "definitions": method.schema["definitions"],
        }
        result.append(
            Tool(
                name=name,
                description=method.id + ": requires an explicit account/context grant.",
                inputSchema=schema,
            )
        )
    for name, (description, params, required, methods) in HELPERS.items():
        if permitted(caller, methods):
            schema = {
                "type": "object",
                "properties": {
                    **base,
                    "params": {
                        "type": "object",
                        "properties": params,
                        "required": required,
                        "additionalProperties": False,
                    },
                },
                "required": ["context", "account", "params"],
                "additionalProperties": False,
            }
            result.append(Tool(name=name, description=description, inputSchema=schema))
    # Own aliases/permissions only; no secret references or foreign account information.
    result.append(
        Tool(
            name="workspace_capabilities",
            description="List your enabled account aliases and permitted methods.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        )
    )
    return result


def build_server(gateway: Gateway) -> Server:
    server = Server("g-utils")

    @server.list_tools()
    async def list_tools():
        return tools(caller_context.get())

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        caller = caller_context.get()
        try:
            if name == "workspace_capabilities":
                result: dict[str, Any] = {}
                for context, ctx in caller.policy.contexts.items():
                    for account, grant in ctx.grants.get(caller.principal, {}).items():
                        methods = [
                            m for m in grant.allow if permitted_for(caller, context, account, m)
                        ]
                        if methods:
                            result.setdefault(context, {})[account] = methods
            else:
                result = await anyio.to_thread.run_sync(
                    lambda: gateway.call(caller, name, **arguments)
                )
            return CallToolResult(
                content=[TextContent(type="text", text=__import__("json").dumps(result))],
                structuredContent=result,
            )
        except AppError as exc:
            return CallToolResult(
                isError=True, content=[TextContent(type="text", text=exc.code + ": " + exc.message)]
            )
        except Exception:
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text="upstream_failure: Operation failed")],
            )

    return server


def permitted_for(caller: Caller, context: str, account: str, method: str) -> bool:
    try:
        authorize(caller.policy, caller.principal, context, account, method)
        return True
    except AppError:
        return False
