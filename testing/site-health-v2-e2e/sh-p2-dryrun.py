#!/usr/bin/env python3
"""Dry-run: extract facts + classify + evaluate the fixture pages.

Fetches each fixture page through the public tunnel (real delivery facts),
runs the P2 parser/classifier/rule catalog exactly as the worker does, and
prints the outcome matrix used as the e2e expectation baseline.

Run from backend/:  uv run python /tmp/sh-p2-dryrun.py [--json]
"""
from __future__ import annotations

import json
import sys
import urllib.request

from app.analysis.site_health.page_types import classify
from app.analysis.site_health.parser import extract_page_facts
from app.analysis.site_health.rules import evaluate_all
from app.analysis.site_health.scoring import score_analysis

BASE = "https://swk5bwh3qdbz.preview.us1.vorflux.com"
PAGES = [
    ("/", "homepage"),
    ("/blog/post-1/", "article"),
    ("/pricing/", "pricing"),
    ("/docs/intro/", "docs"),
    ("/faq/", "faq"),
    ("/product/widget/", "product"),
    ("/category/shoes/", "category"),
    ("/about/", "about_contact"),
    ("/misc/plain/", "other"),
    ("/misc/orphan/", "other"),
]

# The site_facts the worker should build from fixture variant A robots.txt.
EXPECTED_SITE_FACTS = {
    "robots": {
        "fetched": True,
        "ai_crawlers": {
            "GPTBot": "block",
            "ClaudeBot": "allow",
            "PerplexityBot": "allow",
            "Google-Extended": "allow",
        },
    },
    "llms_txt": {"fetched": True, "present": True},
}


def fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "dryrun"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read(), dict(resp.headers), resp.status


def main() -> int:
    as_json = "--json" in sys.argv
    matrix: dict[str, dict] = {}
    type_ok = True
    for path, expected_type in PAGES:
        url = BASE + path
        body, headers, status = fetch(url)
        facts = extract_page_facts(
            body,
            final_url=url,
            content_type=headers.get("Content-Type", ""),
            status_code=status,
            redacted_headers={k.lower(): v for k, v in headers.items()},
            http_version="HTTP/1.1",
            ttfb_ms=50,
            latency_ms=100,
            wire_bytes=len(body),
            decoded_bytes=len(body),
        )
        assessment = classify(url, facts)
        facts["page_type"] = assessment.page_type
        facts["page_type_evidence"] = assessment.to_evidence()
        is_root = path == "/"
        if is_root:
            facts["site"] = EXPECTED_SITE_FACTS
        evals = evaluate_all(facts)
        scores = score_analysis(evals)
        row = {
            "expected_type": expected_type,
            "page_type": assessment.page_type,
            "type_match": assessment.page_type == expected_type,
            "word_count": (facts.get("body") or {}).get("word_count"),
            "scores": {
                "technical_score": scores.technical_score,
                "aeo_score": scores.aeo_score,
                "overall_score": scores.overall_score,
                "scoring_version": scores.scoring_version,
            },
            "evaluations": {
                ev.rule_id: {"outcome": ev.outcome, "weight": ev.weight,
                             "severity": ev.severity, "dimension": ev.dimension,
                             "category": ev.category,
                             "evidence": ev.evidence}
                for ev in evals
            },
        }
        matrix[path] = row
        type_ok = type_ok and row["type_match"]

    if as_json:
        print(json.dumps(matrix, indent=1, default=str))
        return 0 if type_ok else 1

    for path, row in matrix.items():
        flag = "OK " if row["type_match"] else "MISMATCH"
        print(f"\n=== {path}  [{flag} type={row['page_type']} (want {row['expected_type']})] "
              f"words={row['word_count']} scores={row['scores']}")
        for rule_id, ev in sorted(row["evaluations"].items()):
            mark = {"pass": "P", "fail": "F", "not_applicable": "-", "error": "E"}.get(ev["outcome"], "?")
            print(f"  [{mark}] {rule_id:42s} w={ev['weight']:<3} {ev['outcome']}")
    print("\nALL TYPES OK" if type_ok else "\nTYPE MISMATCHES PRESENT")
    return 0 if type_ok else 1


if __name__ == "__main__":
    sys.exit(main())
