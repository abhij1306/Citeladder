#!/usr/bin/env python3
"""P2 e2e — Suite C: robots.txt denies the crawler's own user-agent.

Precondition: /tmp/sh-fixture/robots.txt has been swapped to the deny variant
B (User-agent: SearchifySiteHealthBot / Disallow: /).

Expected: the root fetch is robots_denied; the crawl terminalizes FAILED with
zero analyses; site_facts is still persisted on the crawl row (robots WAS
fetched); llms.txt is not probed (the policy denies it); no page rows exist,
so site_root rule evaluations are simply absent (never fabricated).

Run from backend/:  uv run python /tmp/sh-p2-e2e-negative.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/tmp")
from sh_p2_lib import (  # noqa: E402
    Api, check, create_crawl, create_project, list_all, register_or_login,
    summary, wait_crawl,
)


def main() -> int:
    api = Api()
    print("== auth + seed (variant B robots must be in place)")
    register_or_login(api)
    project_id = create_project(api, "Fixture Co P2 Robots Deny")
    print(f"  project {project_id}")

    print("== crawl (robots_denied expected)")
    crawl_id = create_crawl(api, project_id)
    print(f"  crawl {crawl_id}")
    crawl = wait_crawl(api, crawl_id)

    print("== C1: terminal state")
    check("crawl status failed (root fetch denied)",
          crawl["status"] == "failed", f"status={crawl['status']}")
    check("discovery failed", crawl["discovery_status"] == "failed",
          crawl["discovery_status"])
    check("analyzed_count == 0", crawl["analyzed_count"] == 0,
          str(crawl["analyzed_count"]))
    check("failed_count == 1", crawl["failed_count"] == 1,
          str(crawl["failed_count"]))

    print("== C2: site_facts still persisted (robots fetched; llms not probed)")
    facts = crawl.get("site_facts") or {}
    robots = facts.get("robots") or {}
    check("site_facts present despite failed root", bool(facts))
    check("robots fetched", robots.get("fetched") is True, json_dump(robots))
    stance = robots.get("ai_crawlers") or {}
    check("variant B body -> all AI bots allowed by stance",
          all(stance.get(bot) == "allow" for bot in
              ("GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended")),
          json_dump(stance))
    llms = facts.get("llms_txt") or {}
    check("llms.txt NOT probed (policy denies our UA)",
          llms.get("fetched") is False and llms.get("present") is False,
          json_dump(llms))

    print("== C3: no analyses -> no site_root evaluations (absent, not fabricated)")
    pages = list_all(api, f"/site-crawls/{crawl_id}/pages")
    check("zero page rows", len(pages) == 0, f"got {len(pages)}")
    code, issues = api.get(f"/site-crawls/{crawl_id}/issues?limit=100")
    check("issues endpoint 200 with zero issues",
          code == 200 and issues["summary"]["issue_count"] == 0,
          f"code={code} count={issues.get('summary', {}).get('issue_count')}")

    return summary("Suite C (robots deny)")


def json_dump(obj) -> str:
    import json
    return json.dumps(obj)[:250]


if __name__ == "__main__":
    sys.exit(main())
