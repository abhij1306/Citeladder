#!/usr/bin/env bash
# Suite D wrapper: grant the workspace the Starter capability, run the
# Starter e2e (sitemap ingestion + monitored set + finalize pass), then
# ALWAYS reset the entitlement back to free.
set -uo pipefail
WS=$(docker exec crawlerai-db-1 psql -U postgres -d searchify -tAc "SELECT id FROM workspaces ORDER BY created_at LIMIT 1")
echo "workspace: $WS"
cd /code/abhij1306/Searchify/backend
reset() { uv run python -m scripts.set_site_health_entitlement "$WS" free; }
trap reset EXIT
uv run python -m scripts.set_site_health_entitlement "$WS" starter
uv run python /tmp/sh-p2-e2e-starter.py
