"""MCP tools: one generic tool per Google method, the hand-written tools, and capabilities."""

import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass

import anyio
from jsonschema import Draft7Validator
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool

from .config import MAX_RESULT_BYTES
from .services import drive, gmail
from .utils import auth
from .utils.helpers import AppError, build_client, call, forbidden, method_schema, validate

logger = logging.getLogger("g_utils_mcp")
GENERIC = {m.replace(".", "_"): m for m in gmail.METHODS + drive.METHODS}
CUSTOM = {**gmail.TOOLS, **drive.TOOLS}


@dataclass(frozen=True)
class Caller:
    principal: str
    policy: auth.Policy
    secret: dict


caller: ContextVar[Caller] = ContextVar("caller")


def _schema(params: dict, extra: dict | None = None) -> dict:
    return {
        "type": "object",
        "properties": {
            "context": {"type": "string"},
            "account": {"type": "string"},
            "params": params,
            **(extra or {}),
        },
        "required": ["context", "account", "params"],
        "additionalProperties": False,
    }


def list_tools(who: Caller) -> list[Tool]:
    tools = []
    for name, method_id in GENERIC.items():
        if auth.permitted(who.policy, who.principal, [method_id]):
            schema = method_schema(method_id)
            params = {k: v for k, v in schema.items() if k != "definitions"}
            extra = (
                {"expected_revision": {"type": "string"}} if name.endswith("drafts_update") else {}
            )
            tools.append(
                Tool(
                    name=name,
                    description=method_id + " (Google API). Needs a grant for context/account.",
                    inputSchema={**_schema(params, extra), "definitions": schema["definitions"]},
                )
            )
    for name, (description, properties, required, methods, _) in CUSTOM.items():
        if auth.permitted(who.policy, who.principal, methods):
            custom = {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            }
            tools.append(Tool(name=name, description=description, inputSchema=_schema(custom)))
    tools.append(
        Tool(
            name="workspace_capabilities",
            description="List your account aliases and the methods you may use on each.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        )
    )
    return tools


def runner(who: Caller, context: str, account: str, clients=None):
    """run(method_id, params, media) that authorizes, validates and constrains every call."""

    def run(method_id: str, params: dict, media=None):
        grant = auth.authorize(who.policy, who.principal, context, account, method_id)
        api = method_id.split(".")[0]
        if api == "gmail":
            params = {"userId": "me", **params}  # constrain() rejects any other mailbox
        if method_id in GENERIC.values():
            validate(method_id, params)
        auth.constrain(method_id, params, grant)
        if clients is not None:  # tests inject fake clients
            client = clients(api)
        else:
            creds = auth.credentials(who.policy, who.secret, account, auth.service_of(method_id))
            client = build_client(api, creds)
        try:
            return call(client, method_id, params, media)
        finally:
            if hasattr(client, "close"):
                client.close()

    return run


def capabilities(who: Caller) -> dict:
    result: dict = {}
    for context, ctx in who.policy.contexts.items():
        for account, grant in ctx.grants.get(who.principal, {}).items():
            methods = []
            for method in grant.allow:
                try:
                    auth.authorize(who.policy, who.principal, context, account, method)
                    methods.append(method)
                except AppError:
                    pass
            if methods:
                result.setdefault(context, {})[account] = methods
    return result


def call_tool(who: Caller, name: str, arguments: dict, clients=None) -> dict:
    if name == "workspace_capabilities":
        return capabilities(who)
    context, account = arguments.get("context", ""), arguments.get("account", "")
    params = arguments.get("params", {})
    if not isinstance(params, dict) or account not in who.policy.accounts:
        raise forbidden()
    run = runner(who, context, account, clients)
    if name in CUSTOM:
        _, properties, required, _, function = CUSTOM[name]
        schema = {"type": "object", "properties": properties, "required": required}
        if next(
            Draft7Validator({**schema, "additionalProperties": False}).iter_errors(params), None
        ):
            raise AppError("invalid_input", "Arguments do not match the tool schema", 400)
        result = function(run, params, who.policy.accounts[account].expected_email)
    elif name in GENERIC:
        method_id = GENERIC[name]
        if method_id == "gmail.users.drafts.get":
            result = gmail.summarize(gmail.get_draft(run, params.get("id", "")))
        else:
            if method_id == "gmail.users.drafts.update":
                current = gmail.get_draft(run, params.get("id", ""))
                raw = gmail.decode_raw(current["message"]["raw"])
                if gmail.revision(raw) != arguments.get("expected_revision"):
                    raise AppError("conflict", "Read the draft again; its revision changed", 409)
            result = run(method_id, params)
    else:
        raise forbidden()
    if len(json.dumps(result).encode()) > MAX_RESULT_BYTES:
        raise AppError("too_large", "Result too large; use fields or smaller pages", 413)
    return result


def build_server() -> Server:
    server = Server("g-utils-mcp")

    @server.list_tools()
    async def _list_tools():
        return list_tools(caller.get())

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict):
        who, started, error = caller.get(), time.monotonic(), ""
        try:
            result = await anyio.to_thread.run_sync(lambda: call_tool(who, name, arguments))
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result))],
                structuredContent=result,
            )
        except AppError as exc:
            error = exc.code
            return CallToolResult(
                isError=True, content=[TextContent(type="text", text=f"{exc.code}: {exc.message}")]
            )
        except Exception:
            error = "upstream_failure"
            return CallToolResult(
                isError=True, content=[TextContent(type="text", text="upstream_failure")]
            )
        finally:
            # Names and outcome only: never arguments, results or credentials.
            logger.warning(
                json.dumps(
                    {
                        "principal": who.principal,
                        "tool": name,
                        "account": str(arguments.get("account", ""))[:80],
                        "error": error,
                        "ms": round((time.monotonic() - started) * 1000),
                    }
                )
            )

    return server
