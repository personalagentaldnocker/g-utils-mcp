FROM ghcr.io/astral-sh/uv:0.12.23 AS uv
FROM python:3.12.14-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
RUN uv sync --locked --no-dev --no-editable --compile-bytecode
RUN chmod -R a+rX /app/.venv

FROM python:3.12.14-slim AS runtime
RUN useradd --uid 10001 --create-home app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PORT=8080
USER 10001
EXPOSE 8080
CMD ["g-utils-mcp", "serve"]
