# CiteLadder Next.js standalone image.
# Build from the repository root:
# docker build -f infra/aws/frontend.Dockerfile --build-arg BACKEND_ORIGIN=http://api:8000 .

FROM node:22-bookworm-slim AS dependencies

ENV COREPACK_HOME=/corepack
WORKDIR /app

RUN corepack enable \
    && corepack prepare pnpm@11.9.0 --activate

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM dependencies AS builder

COPY frontend/ ./

ARG BACKEND_ORIGIN
ENV NODE_ENV=production \
    BACKEND_ORIGIN=$BACKEND_ORIGIN

RUN test -n "$BACKEND_ORIGIN" \
    && pnpm build

FROM node:22-bookworm-slim AS runtime

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000

WORKDIR /app

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

USER node

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r => process.exit(r.status < 500 ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "server.js"]

