# Runtime interpreter. Pinned to 3.12 so the image, backend/.python-version,
# the CI gate, and the `requires-python` floor are one version: a Dependabot
# bump had moved this to 3.14 while every gate still validated 3.12, so the
# container shipped an interpreter nothing tested. Bump all four together.
FROM python:3.12.14-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134 AS dependencies

ARG UV_VERSION=0.11.28
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/backend

# Native toolchains exist only in the dependency stage; the runtime image does
# not contain a compiler or development headers.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install "uv==${UV_VERSION}"

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12.14-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134 AS runtime

ARG BUILD_REVISION=unknown
LABEL org.opencontainers.image.title="citeladder-backend" \
      org.opencontainers.image.revision="${BUILD_REVISION}"

ENV PATH="/app/backend/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

RUN groupadd --gid 10001 appuser \
    && useradd --no-create-home --uid 10001 --gid 10001 --shell /usr/sbin/nologin appuser \
    && install -d -o 10001 -g 10001 /app/backend/.runtime

# Dependencies and source remain root-owned/read-only to the runtime identity.
COPY --from=dependencies --chown=0:0 /app/backend/.venv ./.venv

COPY --chown=0:0 backend/app ./app
COPY --chown=0:0 backend/alembic.ini ./alembic.ini
COPY --chown=0:0 migrations /app/migrations

USER 10001:10001

EXPOSE 8000

# Orchestrator readiness probe. /ready (not /health) because an orchestrator
# uses this to decide whether to send traffic: a container whose database is
# unreachable answers /health with 200 and would keep taking requests it
# cannot serve. /ready returns 503 in exactly that case.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
