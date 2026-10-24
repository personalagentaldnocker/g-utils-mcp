from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import anyio
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .artifacts import Artifacts
from .config import Settings
from .credentials.google_oauth import GoogleClients
from .credentials.secrets import GCPSecrets
from .errors import AppError, forbidden
from .gateway import Caller, Gateway
from .identity import authenticate
from .mcp_server import build_server, caller_context
from .policy.store import PolicyStore
from .storage import GCSStore


def create_app(
    settings: Settings | None = None,
    *,
    policies=None,
    secrets=None,
    artifacts=None,
    clients=None,
    oauth=None,
):
    settings = settings or Settings()
    if policies is None:
        settings.require_cloud()
        uri = urlsplit(settings.policy_uri)
        policies = PolicyStore(GCSStore(uri.netloc), uri.path.lstrip("/"))
    secrets = secrets or GCPSecrets(settings.allowed_secret_projects)
    artifacts = artifacts or Artifacts(
        GCSStore(settings.temp_bucket), settings.max_transfer_bytes, settings.artifact_ttl_seconds
    )
    gateway = Gateway(clients or GoogleClients(secrets), artifacts, settings.max_result_bytes)
    server = build_server(gateway)
    host = urlsplit(settings.public_base_url).netloc
    allowed_hosts = [host] if host else ["127.0.0.1:*", "localhost:*", "testserver"]
    manager = StreamableHTTPSessionManager(
        server,
        stateless=True,
        json_response=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=[settings.public_base_url]
            if host
            else ["http://localhost:*", "http://127.0.0.1:*"],
        ),
    )

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    class MCP:
        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)

    async def health(request):
        return JSONResponse({"status": "ok"})

    async def ready(request):
        await anyio.to_thread.run_sync(policies.current)
        return JSONResponse({"status": "ready"})

    async def upload(request: Request):
        caller = caller_context.get()
        context = request.headers.get("x-workspace-context", "")
        principal = caller.policy.principals[caller.principal]
        if context not in principal.allowed_contexts:
            raise forbidden()
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > artifacts.limit:
                raise AppError("too_large", "File exceeds transfer limit", 413)
        meta = await anyio.to_thread.run_sync(
            lambda: artifacts.create(
                caller.principal,
                context,
                bytes(data),
                request.headers.get("x-filename", "file"),
                request.headers.get("content-type", "application/octet-stream"),
            )
        )
        return JSONResponse(meta, status_code=201)

    async def download(request):
        caller = caller_context.get()
        context = request.headers.get("x-workspace-context", "")
        if context not in caller.policy.principals[caller.principal].allowed_contexts:
            raise forbidden()
        meta, data = await anyio.to_thread.run_sync(
            lambda: gateway.artifact(caller, context, request.path_params["ref"])
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

    async def oauth_route(request):
        nonlocal oauth
        if not settings.public_base_url:
            raise AppError("unavailable", "Enrollment is not configured yet", 503)
        if oauth is None:
            from .oauth.routes import Enrollment

            oauth = Enrollment(settings, policies, secrets, artifacts.store)
        return await anyio.to_thread.run_sync(
            lambda: oauth.handle(request.url.path, dict(request.query_params))
        )

    inner = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/healthz", health),
            Route("/readyz", ready),
            Route("/mcp", MCP(), methods=["POST", "GET", "DELETE"]),
            Route("/artifacts", upload, methods=["POST"]),
            Route("/artifacts/{ref}", download),
            Route("/oauth/google/start", oauth_route),
            Route("/oauth/google/callback", oauth_route),
        ],
    )

    class Security:
        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await inner(scope, receive, send)
            token = None
            try:
                path = scope["path"]
                headers = {k.lower(): v for k, v in scope["headers"]}
                if path not in ("/healthz", "/oauth/google/start", "/oauth/google/callback"):
                    snapshot = await anyio.to_thread.run_sync(policies.current)
                    principal = await anyio.to_thread.run_sync(
                        lambda: authenticate(
                            snapshot.policy, secrets, headers.get(b"authorization", b"").decode()
                        )
                    )
                    token = caller_context.set(
                        Caller(principal, snapshot.policy, snapshot.generation)
                    )
                await inner(scope, receive, send)
            except AppError as exc:
                await JSONResponse(
                    {"error": exc.code, "message": exc.message},
                    status_code=exc.status,
                    headers={"Cache-Control": "no-store"},
                )(scope, receive, send)
            except Exception:
                await JSONResponse(
                    {"error": "unavailable", "message": "Service unavailable"}, status_code=503
                )(scope, receive, send)
            finally:
                if token is not None:
                    caller_context.reset(token)

    return Security()
