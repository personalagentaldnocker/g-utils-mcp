"""Cloud Run entry point: /healthz, and the authenticated /mcp and /files endpoints."""

import hashlib
import os
from contextlib import asynccontextmanager
from urllib.parse import quote, unquote

import anyio
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import config
from .mcp_server import Caller, build_server, caller
from .utils import auth
from .utils.helpers import AppError, file_load, file_store


def load_caller(authorization: str) -> Caller:
    """Policy first (checked every request), then the token against the secret."""
    policy = auth.current_policy(config.policy_uri())
    secret = auth.current_secret(config.secret_name())
    return Caller(auth.authenticate(authorization, policy, secret), policy, secret)


class ASGI:
    """Starlette treats plain functions as request handlers; this passes raw ASGI through."""

    def __init__(self, handler):
        self.handler = handler

    async def __call__(self, scope, receive, send):
        await self.handler(scope, receive, send)


def create_app(load=load_caller):
    manager = StreamableHTTPSessionManager(
        build_server(),
        stateless=True,
        json_response=True,
        # Bearer authentication on a public HTTPS endpoint; DNS rebinding targets local servers.
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    async def health(request):
        return JSONResponse({"status": "ok"})

    def error(exc: Exception) -> JSONResponse:
        if isinstance(exc, AppError):
            body, status = {"error": exc.code, "message": exc.message}, exc.status
        else:  # missing settings or Google Cloud unreachable; no details out
            body, status = {"error": "unavailable"}, 503
        return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})

    async def file_upload(request: Request):
        """POST raw bytes (X-Filename, Content-Type headers) -> file_ref for the tools."""
        try:
            who = await anyio.to_thread.run_sync(
                lambda: load(request.headers.get("authorization", ""))
            )
            data = bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > config.MAX_FILE_BYTES:
                    raise AppError("too_large", "File exceeds the size limit", 413)
            name = unquote(request.headers.get("x-filename", "file"))
            mime_type = request.headers.get("content-type", "application/octet-stream")
            ref = await anyio.to_thread.run_sync(
                lambda: file_store(who.principal, bytes(data), name, mime_type)
            )
        except Exception as exc:
            return error(exc)
        digest = hashlib.sha256(data).hexdigest()
        return JSONResponse({"file_ref": ref, "size": len(data), "sha256": digest}, status_code=201)

    async def file_download(request: Request):
        """GET the bytes behind a file_ref returned by a tool."""
        try:
            who = await anyio.to_thread.run_sync(
                lambda: load(request.headers.get("authorization", ""))
            )
            ref = request.path_params["ref"]
            data, name, mime_type = await anyio.to_thread.run_sync(
                lambda: file_load(who.principal, ref)
            )
        except Exception as exc:
            return error(exc)
        headers = {
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name),
            "X-Content-SHA256": hashlib.sha256(data).hexdigest(),
            "Cache-Control": "no-store",
        }
        return Response(data, media_type=mime_type, headers=headers)

    async def mcp(scope, receive, send):
        headers = {k.lower(): v for k, v in scope["headers"]}
        token = None
        try:
            authorization = headers.get(b"authorization", b"").decode()
            who = await anyio.to_thread.run_sync(lambda: load(authorization))
            token = caller.set(who)
            await manager.handle_request(scope, receive, send)
        except Exception as exc:
            await error(exc)(scope, receive, send)
        finally:
            if token is not None:
                caller.reset(token)

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    return Starlette(
        lifespan=lifespan,
        routes=[
            Route("/health", health),
            Route("/healthz", health),
            Route("/mcp", ASGI(mcp), methods=["POST", "GET", "DELETE"]),
            Route("/files", file_upload, methods=["POST"]),
            Route("/files/{ref}", file_download, methods=["GET"]),
        ],
    )


def main():
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
