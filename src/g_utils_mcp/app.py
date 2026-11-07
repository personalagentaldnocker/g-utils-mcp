"""Cloud Run entry point: /healthz and the authenticated /mcp endpoint."""

import os
from contextlib import asynccontextmanager

import anyio
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import config
from .mcp_server import Caller, build_server, caller
from .utils import auth
from .utils.helpers import AppError


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

    async def mcp(scope, receive, send):
        headers = {k.lower(): v for k, v in scope["headers"]}
        token = None
        try:
            authorization = headers.get(b"authorization", b"").decode()
            who = await anyio.to_thread.run_sync(lambda: load(authorization))
            token = caller.set(who)
            await manager.handle_request(scope, receive, send)
        except AppError as exc:
            response = JSONResponse(
                {"error": exc.code, "message": exc.message},
                status_code=exc.status,
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
        except Exception:  # missing settings or Secret Manager unreachable; no details out
            await JSONResponse({"error": "unavailable"}, status_code=503)(scope, receive, send)
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
        ],
    )


def main():
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
