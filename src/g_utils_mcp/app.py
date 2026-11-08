"""MCP server and HTTP routes.

Request flow: authenticate the bearer token against the current policy generation, list or
run only the tools the policy grants, and reach Google only through policy.run().
"""

import json
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

import anyio
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import drive, gmail, policy, utils
from .policy import Caller
from .utils import AppError

METHODS = {policy.tool_name(m): m for m in gmail.METHODS + drive.METHODS}
OVERRIDES = {**gmail.OVERRIDES}
HELPERS = {**gmail.HELPERS, **drive.HELPERS}
CAPABILITIES = "workspace_capabilities"
# Every name a policy may grant. Adding a tool here never grants it to anyone.
KNOWN = set(METHODS) | set(HELPERS) | drive.PERMISSIONS
caller_var: ContextVar[Caller] = ContextVar("caller")


def tool_schema(name: str) -> dict:
    account = {"account": {"type": "string", "description": "Account alias from the policy"}}
    if name in METHODS:
        schema = utils.method_schema(METHODS[name])
        params = {k: v for k, v in schema.items() if k != "definitions"}
        # Gmail's userId is always "me"; the server fills it in.
        params["required"] = [r for r in params["required"] if r != "userId"]
        return {
            "type": "object",
            "properties": {
                **account,
                "params": params,
                "expected_revision": {"type": "string"},
                "filename": {"type": "string"},
            },
            "required": ["account", "params"],
            "additionalProperties": False,
            "definitions": schema["definitions"],
        }
    _, properties, required, _ = HELPERS[name]
    params = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {**account, "params": params},
        "required": ["account", "params"],
        "additionalProperties": False,
    }


def list_tools(caller: Caller) -> list[Tool]:
    granted = {t for names in policy.tools_for(caller).values() for t in names}
    tools = []
    for name in sorted(granted & (set(METHODS) | set(HELPERS))):
        if name in METHODS:
            description = METHODS[name] + " (Google API method)."
        else:
            description = HELPERS[name][0]
        tools.append(Tool(name=name, description=description, inputSchema=tool_schema(name)))
    tools.append(
        Tool(
            name=CAPABILITIES,
            description="List your account aliases and the tools you may use on each.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        )
    )
    return tools


def call_tool(caller: Caller, name: str, arguments: dict) -> Any:
    """Run one tool call. Every path checks the policy before touching credentials."""
    if name == CAPABILITIES:
        return policy.tools_for(caller)
    account, params = arguments.get("account", ""), arguments.get("params", {})
    if not isinstance(account, str) or not isinstance(params, dict):
        raise AppError("invalid_input", "account must be a string and params an object", 400)
    if name in HELPERS:
        result = HELPERS[name][3](caller, account, params)
    elif name in METHODS:
        method = METHODS[name]
        if method in OVERRIDES:
            policy.check(caller, account, name)
            result = OVERRIDES[method](caller, account, params, arguments)
        else:
            result = policy.run(caller, account, method, params)
    else:
        raise AppError()
    if len(json.dumps(result).encode()) > utils.RESULT_LIMIT:
        raise AppError("too_large", "Result too large; use fields or smaller pages", 413)
    return result


def logged_call(caller: Caller, name: str, arguments: dict) -> Any:
    started, error = time.monotonic(), ""
    try:
        return call_tool(caller, name, arguments)
    except AppError as exc:
        error = exc.code
        raise
    except Exception:
        error = "internal"
        raise
    finally:
        account = arguments.get("account")
        utils.log(
            event="tool_call",
            principal=caller.principal,
            account=account if account in caller.policy["accounts"] else "unknown",
            tool=name if name in KNOWN or name == CAPABILITIES else "unknown",
            generation=caller.generation,
            error=error,
            duration_ms=round((time.monotonic() - started) * 1000),
        )


def mcp_server() -> Server:
    server = Server("g-utils-mcp")

    @server.list_tools()
    async def _list_tools():
        return list_tools(caller_var.get())

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict):
        caller = caller_var.get()
        try:
            result = await anyio.to_thread.run_sync(lambda: logged_call(caller, name, arguments))
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result))],
                structuredContent=result,
            )
        except AppError as exc:
            text = exc.code + ": " + exc.message
        except Exception:
            text = "upstream_failure: Operation failed"
        return CallToolResult(isError=True, content=[TextContent(type="text", text=text)])

    return server


def default_policy() -> Callable[[], tuple[dict, int]]:
    uri = os.environ.get("POLICY_URI", "")
    if not uri.startswith("gs://") or "/" not in uri[5:]:
        raise ValueError("Set POLICY_URI=gs://bucket/object")
    name, key = uri[5:].split("/", 1)
    return policy.loader(utils.bucket(name).blob(key), KNOWN)


def create_app(current_policy: Callable[[], tuple[dict, int]] | None = None):
    current = current_policy or default_policy()
    current()  # Fail at startup when the policy is missing or invalid.
    manager = StreamableHTTPSessionManager(
        mcp_server(),
        stateless=True,
        json_response=True,
        # Browsers cannot attach the bearer token, so DNS rebinding cannot authenticate.
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    async def health(request: Request):
        return JSONResponse({"status": "ok"})

    async def ready(request: Request):
        await anyio.to_thread.run_sync(current)
        return JSONResponse({"status": "ready"})

    async def upload(request: Request):
        """Store request bytes as a temporary file so they never pass through the model."""
        caller = caller_var.get()
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > utils.TRANSFER_LIMIT:
                raise AppError("too_large", "File exceeds transfer limit", 413)
        name = request.headers.get("x-filename", "file")
        mime = request.headers.get("content-type", "application/octet-stream")
        meta = await anyio.to_thread.run_sync(
            lambda: utils.put_file(caller.principal, "", bytes(data), name, mime, "http_upload")
        )
        return JSONResponse(meta, status_code=201)

    async def download(request: Request):
        caller = caller_var.get()
        ref = request.path_params["ref"]
        meta, data = await anyio.to_thread.run_sync(
            lambda: policy.get_file(caller, ref, "http_download")
        )
        return Response(
            data,
            media_type=meta["mime_type"],
            headers={
                "Content-Disposition": 'attachment; filename="' + meta["filename"] + '"',
                "X-Content-SHA256": meta["sha256"],
                "Cache-Control": "no-store",
            },
        )

    async def app_error(request: Request, exc: Exception):
        assert isinstance(exc, AppError)
        body = {"error": exc.code, "message": exc.message}
        return JSONResponse(body, exc.status, headers={"Cache-Control": "no-store"})

    routes = Starlette(
        lifespan=lifespan,
        exception_handlers={AppError: app_error},
        routes=[
            Route("/healthz", health),
            Route("/readyz", ready),
            Route("/files", upload, methods=["POST"]),
            Route("/files/{ref}", download),
        ],
    )

    async def app(scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/healthz":
            return await routes(scope, receive, send)
        reset = None
        try:
            headers = {k.lower(): v for k, v in scope["headers"]}
            authorization = headers.get(b"authorization", b"").decode()
            policy_now, generation = await anyio.to_thread.run_sync(current)
            principal = policy.authenticate(policy_now, authorization)
            reset = caller_var.set(Caller(principal, policy_now, generation))
            if scope["path"] == "/mcp":
                await manager.handle_request(scope, receive, send)
            else:
                await routes(scope, receive, send)
        except AppError as exc:
            body = {"error": exc.code, "message": exc.message}
            response = JSONResponse(body, exc.status, headers={"Cache-Control": "no-store"})
            await response(scope, receive, send)
        except Exception:
            body = {"error": "unavailable", "message": "Service unavailable"}
            await JSONResponse(body, 503)(scope, receive, send)
        finally:
            if reset is not None:
                caller_var.reset(reset)

    return app
