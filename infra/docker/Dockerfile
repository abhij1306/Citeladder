FROM python:3.14.7-slim-bookworm@sha256:23c59390fc717bf09f9336908199a0ae75d9c4264bf296123f94ad772fea3b52 AS dependencies

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

FROM python:3.14.7-slim-bookworm@sha256:23c59390fc717bf09f9336908199a0ae75d9c4264bf296123f94ad772fea3b52 AS runtime

ARG BUILD_REVISION=unknown
LABEL org.opencontainers.image.title="citeladder-backend" \
      org.opencontainers.image.revision="${BUILD_REVISION}"

# Acquisition rung 3 (Patchright) needs a Chromium build plus its shared
# libraries — roughly 400 MB the default image should not carry, because
# ``browser_enabled`` defaults to False and most deployments never render a
# page. Build with ``--build-arg INSTALL_BROWSER_RUNG=true`` for a deployment
# that turns rung 3 on. Without it the transport fails closed with
# ``acquisition_unavailable`` and the crawl keeps its server evidence.
ARG INSTALL_BROWSER_RUNG=false

ENV PATH="/app/backend/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

WORKDIR /app/backend

RUN groupadd --gid 10001 appuser \
    && useradd --no-create-home --uid 10001 --gid 10001 --shell /usr/sbin/nologin appuser \
    && install -d -o 10001 -g 10001 /app/backend/.runtime

# Dependencies and source remain root-owned/read-only to the runtime identity.
COPY --from=dependencies --chown=0:0 /app/backend/.venv ./.venv

# Installed as root into a shared path (the runtime user has no home
# directory), and left read-only to that user: the crawler executes the browser
# but must never be able to replace the binary it executes.
RUN if [ "${INSTALL_BROWSER_RUNG}" = "true" ]; then \
      patchright install --with-deps chromium \
      && rm -rf /var/lib/apt/lists/* \
      # Prove the browser actually launches at BUILD time. A missing shared
      # library surfaces only on first use otherwise — as an
      # ``acquisition_unavailable`` on a live crawl, which the ladder treats as
      # "keep the prior evidence" and therefore never reports as broken. The
      # sandbox is disabled for this probe only (docker build has no user
      # namespace); the runtime keeps it on unless explicitly opted out.
      && python -c "\
from patchright.sync_api import sync_playwright;\
p = sync_playwright().start();\
b = p.chromium.launch(headless=True, args=['--no-sandbox']);\
b.close();\
p.stop();\
print('chromium launch OK as root')" \
      # Then prove it again AS THE RUNTIME IDENTITY. A root launch says nothing
      # about uid 10001: the install above is deliberately read-only to that
      # user, so one missing execute bit under /opt/ms-playwright passes the
      # root probe and fails every live crawl — the exact silent failure this
      # probe exists to catch.
      && runuser -u appuser -- python -c "\
from patchright.sync_api import sync_playwright;\
p = sync_playwright().start();\
b = p.chromium.launch(headless=True, args=['--no-sandbox']);\
b.close();\
p.stop();\
print('chromium launch OK as appuser')"; \
    fi
COPY --chown=0:0 backend/app ./app
COPY --chown=0:0 backend/alembic.ini ./alembic.ini
COPY --chown=0:0 migrations /app/migrations

USER 10001:10001

EXPOSE 8000

# Orchestrator liveness probe against the app's /health route.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
