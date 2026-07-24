#!/usr/bin/env bash
# Test-only seed for Site Health v2 P1 E2E (NOT for the repo).
# Registers a fresh user and creates a project pointing at the public fixture
# tunnel. Idempotent per email (register 409 -> falls back to login).
set -euo pipefail
BASE="${BASE:-http://localhost:8000/api/v1}"
FIXTURE_URL="${FIXTURE_URL:-https://swk5bwh3qdbz.preview.us1.vorflux.com/}"
EMAIL="sh-p1-test@searchify.dev"
PASS="ShP1Test!2026Secure#Pass"
JAR=/tmp/sh-cookies.txt
rm -f "$JAR"

code=$(curl -s -o /tmp/sh-register.json -w "%{http_code}" -c "$JAR" \
  -X POST "$BASE/auth/register" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}")
if [ "$code" != "201" ] && [ "$code" != "200" ]; then
  echo "register returned $code; trying login"
  curl -s -o /tmp/sh-login.json -w "login: %{http_code}\n" -c "$JAR" \
    -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}"
else
  echo "registered: $code"
fi

curl -s -b "$JAR" "$BASE/auth/me" | head -c 300; echo

code=$(curl -s -o /tmp/sh-project.json -w "%{http_code}" -b "$JAR" \
  -X POST "$BASE/projects" -H 'Content-Type: application/json' \
  -d "{\"name\":\"Fixture Co Site Health\",\"brand_name\":\"Fixture Co\",\"website_url\":\"$FIXTURE_URL\"}")
echo "project create: $code"
cat /tmp/sh-project.json | head -c 500; echo
