FROM node:26.8.1-bookworm-slim@sha256:367679cf9792759492a486e4aa4b421764d71a9546a6dae8aab81a99eb797b3e AS dependencies

ENV PNPM_HOME=/pnpm
ENV PATH="${PNPM_HOME}:${PATH}"
WORKDIR /app

# Node 26 no longer bundles corepack, so pnpm is installed from npm.
# Keep this version in lockstep with `packageManager` in frontend/package.json.
RUN npm install --global --ignore-scripts pnpm@11.22.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile --ignore-scripts

FROM node:26.8.1-bookworm-slim@sha256:367679cf9792759492a486e4aa4b421764d71a9546a6dae8aab81a99eb797b3e AS builder

ARG BACKEND_ORIGIN
ARG CITELADDER_TASK_LOCAL_BACKEND=false
ARG BUILD_REVISION=unknown
# `NEXT_PUBLIC_*` values are inlined into the client bundle by `next build`,
# so they have to exist HERE — supplying them only at container runtime is
# too late for anything rendered in the browser. Each one is optional and the
# reader handles absence (lib/config/env.ts, lib/config/operational.ts), so an
# empty arg produces a working build with the feature simply unconfigured.
# NEXT_PUBLIC_SITE_URL is additionally read server-side (sitemap, robots, OG
# metadata), so the compose frontend service also passes it at runtime.
ARG NEXT_PUBLIC_SITE_URL
ARG NEXT_PUBLIC_LOGO_DEV_PUBLISHABLE
ARG NEXT_PUBLIC_API_REQUEST_TIMEOUT_MS
ARG NEXT_PUBLIC_DEMO_MODE=false
ENV PNPM_HOME=/pnpm
ENV PATH="${PNPM_HOME}:${PATH}"
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV BACKEND_ORIGIN=${BACKEND_ORIGIN}
ENV CITELADDER_TASK_LOCAL_BACKEND=${CITELADDER_TASK_LOCAL_BACKEND}
ENV BUILD_REVISION=${BUILD_REVISION}
ENV NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL}
ENV NEXT_PUBLIC_LOGO_DEV_PUBLISHABLE=${NEXT_PUBLIC_LOGO_DEV_PUBLISHABLE}
ENV NEXT_PUBLIC_API_REQUEST_TIMEOUT_MS=${NEXT_PUBLIC_API_REQUEST_TIMEOUT_MS}
ENV NEXT_PUBLIC_DEMO_MODE=${NEXT_PUBLIC_DEMO_MODE}
WORKDIR /app

# Node 26 no longer bundles corepack, so pnpm is installed from npm.
# Keep this version in lockstep with `packageManager` in frontend/package.json.
RUN npm install --global --ignore-scripts pnpm@11.22.0
COPY --from=dependencies /app/node_modules ./node_modules
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
COPY frontend/app ./app
COPY frontend/components ./components
COPY frontend/lib ./lib
COPY frontend/public ./public
COPY frontend/test ./test
COPY frontend/next.config.ts frontend/postcss.config.mjs frontend/tsconfig.json ./
RUN pnpm build

FROM node:26.8.1-bookworm-slim@sha256:367679cf9792759492a486e4aa4b421764d71a9546a6dae8aab81a99eb797b3e AS runtime

ARG BACKEND_ORIGIN
ARG CITELADDER_TASK_LOCAL_BACKEND=false
ARG BUILD_REVISION=unknown
LABEL org.opencontainers.image.title="citeladder-frontend" \
      org.opencontainers.image.revision="${BUILD_REVISION}"

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    BACKEND_ORIGIN=${BACKEND_ORIGIN} \
    CITELADDER_TASK_LOCAL_BACKEND=${CITELADDER_TASK_LOCAL_BACKEND}
WORKDIR /app

# The official image's `node` account is unprivileged. Standalone output and
# assets remain root-owned; the process needs no write access to application code.
COPY --from=builder --chown=0:0 /app/.next/standalone ./
COPY --from=builder --chown=0:0 /app/.next/static ./.next/static
COPY --from=builder --chown=0:0 /app/public ./public
RUN mkdir -p /app/.next/cache && chown node:node /app/.next/cache

USER node
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/health').then(r=>process.exit(r.ok ? 0 : 1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
