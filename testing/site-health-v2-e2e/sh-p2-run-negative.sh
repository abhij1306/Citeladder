#!/usr/bin/env bash
# Suite C wrapper: swap fixture robots.txt to the deny variant, run the
# negative e2e, ALWAYS restore variant A afterwards.
set -uo pipefail
cp /tmp/sh-fixture/robots.txt /tmp/sh-robots-variantA.bak
restore() { cp /tmp/sh-robots-variantA.bak /tmp/sh-fixture/robots.txt; }
trap restore EXIT
cp /tmp/sh-robots-deny.txt /tmp/sh-fixture/robots.txt
echo "robots.txt swapped to variant B (deny SearchifySiteHealthBot):"
curl -s http://localhost:9900/robots.txt | head -3
cd /code/abhij1306/Searchify/backend
uv run python /tmp/sh-p2-e2e-negative.py
