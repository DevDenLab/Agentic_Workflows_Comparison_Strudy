# syntax=docker/dockerfile:1
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Dependencies first, so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY config ./config
COPY data ./data
RUN uv sync --locked --no-dev

RUN useradd --create-home triage && mkdir -p /var/lib/triage && chown triage /var/lib/triage
USER triage

ENV CONFIG_DIR=/app/config \
    DATA_DIR=/app/data \
    VAR_DIR=/var/lib/triage \
    LOG_FORMAT=json

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
CMD ["uvicorn", "triage.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
