#!/usr/bin/env python3
"""P2 e2e — Suite B: Free sample crawl against the fixture tunnel.

Seeds a fresh user+project, runs a full crawl, and asserts the P2 behavior
through the public API: site_facts stance/llms, per-page new-rule outcomes
(vs the dry-run baseline), site_root weight-0 anchoring, crawl_finalize rows,
grouped issues with display labels, exports, dashboard, and version stamps.

Run from backend/:  uv run python /tmp/sh-p2-e2e-free.py
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/tmp")
from sh_p2_lib import (  # noqa: E402
    Api, FIXTURE_URL, check, create_crawl, create_project, list_all,
    register_or_login, summary, wait_crawl,
)

EXPECT = json.load(open("/tmp/sh-p2-expectations.json"))
FINALIZE_RULES = {
    "technical.broken_internal_link",
    "technical.sitemap_orphan",
    "technical.hreflang_conflict",
}
SITE_ROOT_RULES = {"technical.ai_crawler_access", "aeo.llms_txt_present"}

# Fixture page path -> expected page type (P1 contract, must hold).
PATH_TYPES = {path: row["expected_type"] for path, row in EXPECT.items()
              if path != "/misc/orphan/"}


def main() -> int:
    api = Api()
    print("== auth + seed")
    register_or_login(api)
    project_id = create_project(api, "Fixture Co P2 Free")
    print(f"  project {project_id}")

    print("== crawl (free sample)")
    crawl_id = create_crawl(api, project_id)
    print(f"  crawl {crawl_id}")
    crawl = wait_crawl(api, crawl_id)

    print("== B1: crawl terminal state")
    check("crawl completed", crawl["status"] == "completed",
          f"status={crawl['status']} error={crawl.get('error_message')}")
    check("sample_mode true", crawl["sample_mode"] is True)
    check("analyzed_count == 9", crawl["analyzed_count"] == 9,
          f"analyzed={crawl['analyzed_count']}")
    check("Free non-disclosure: discovered_count redacted",
          crawl["discovered_count"] is None,
          f"discovered_count={crawl['discovered_count']}")

    print("== B2: version stamps")
    check("extractor sh-extractor-2", crawl["extractor_version"] == "sh-extractor-2",
          crawl["extractor_version"])
    check("analyzer sh-analyzer-2", crawl["analyzer_version"] == "sh-analyzer-2",
          crawl["analyzer_version"])
    check("rules sh-rules-2", crawl["rule_version"] == "sh-rules-2",
          crawl["rule_version"])
    check("scoring sh-scoring-2", crawl["scoring_version"] == "sh-scoring-2",
          crawl["scoring_version"])

    print("== B3: site_facts (robots stance + llms.txt)")
    facts = crawl.get("site_facts") or {}
    robots = facts.get("robots") or {}
    check("site_facts present", bool(facts))
    check("robots fetched", robots.get("fetched") is True, json.dumps(robots)[:200])
    check("robots status 200", robots.get("status_code") == 200,
          str(robots.get("status_code")))
    stance = robots.get("ai_crawlers") or {}
    check("GPTBot blocked", stance.get("GPTBot") == "block", json.dumps(stance))
    check("ClaudeBot allowed", stance.get("ClaudeBot") == "allow", json.dumps(stance))
    check("PerplexityBot allowed", stance.get("PerplexityBot") == "allow",
          json.dumps(stance))
    check("Google-Extended allowed (wildcard)", stance.get("Google-Extended") == "allow",
          json.dumps(stance))
    declared = robots.get("sitemaps") or []
    check("robots declares sitemap", any(s.endswith("/sitemap.xml") for s in declared),
          json.dumps(declared))
    llms = facts.get("llms_txt") or {}
    check("llms.txt fetched+present", llms.get("fetched") is True and llms.get("present") is True,
          json.dumps(llms))
    sitemap = facts.get("sitemap") or {}
    check("sitemap ingestion skipped on Free", sitemap.get("fetched") is False,
          json.dumps(sitemap))

    print("== B4: pages + page types")
    pages = list_all(api, f"/site-crawls/{crawl_id}/pages")
    check("9 page rows", len(pages) == 9, f"got {len(pages)}")
    by_path: dict[str, dict] = {}
    for page in pages:
        path = page["normalized_url"].replace(FIXTURE_URL.rstrip("/"), "") or "/"
        if not path.startswith("/"):
            path = "/" + path
        by_path[path] = page
    for path, expected in PATH_TYPES.items():
        page = by_path.get(path)
        check(f"{path} present", page is not None)
        if page:
            check(f"{path} type={expected}", page["page_type"] == expected,
                  f"got {page['page_type']}")
            check(f"{path} analysis completed",
                  page["analysis_status"] == "completed",
                  f"got {page['analysis_status']} err={page['error_code']}")

    print("== B5: per-page evaluations vs dry-run baseline")
    for path, page in sorted(by_path.items()):
        expected = EXPECT.get(path)
        if expected is None:
            continue
        code, detail = api.get(f"/site-crawls/{crawl_id}/pages/{page['site_url_id']}")
        assert code == 200, f"page detail {path}: {code}"
        evals = {ev["rule_id"]: ev for ev in detail["evaluations"]}
        # Every non-finalize rule outcome matches the dry-run baseline.
        mismatches = []
        for rule_id, exp_ev in expected["evaluations"].items():
            if rule_id in FINALIZE_RULES:
                continue
            got = evals.get(rule_id)
            if got is None:
                mismatches.append(f"{rule_id}: missing")
            elif got["outcome"] != exp_ev["outcome"]:
                mismatches.append(
                    f"{rule_id}: api={got['outcome']} want={exp_ev['outcome']}")
        check(f"{path} per-rule outcomes match baseline", not mismatches,
              "; ".join(mismatches[:6]))
        # Scores match the baseline (proves weight-0 site_root fail on the
        # root did not enter any numerator/denominator).
        exp_scores = expected["scores"]
        for dim in ("technical_score", "aeo_score", "overall_score"):
            check(f"{path} {dim} == baseline",
                  detail[dim] == exp_scores[dim],
                  f"api={detail[dim]} want={exp_scores[dim]}")

    print("== B5b: site_root anchoring")
    root = by_path.get("/")
    if root:
        code, detail = api.get(f"/site-crawls/{crawl_id}/pages/{root['site_url_id']}")
        evals = {ev["rule_id"]: ev for ev in detail["evaluations"]}
        ev = evals.get("technical.ai_crawler_access")
        check("root ai_crawler_access FAIL", ev and ev["outcome"] == "fail",
              json.dumps(ev)[:200] if ev else "missing")
        if ev:
            check("root ai_crawler_access weight 0", ev["weight"] == 0.0,
                  str(ev["weight"]))
            blocked = (ev["evidence"] or {}).get("blocked")
            check("root ai_crawler_access evidence blocked=[GPTBot]",
                  blocked == ["GPTBot"], json.dumps(blocked))
        ev = evals.get("aeo.llms_txt_present")
        check("root llms_txt_present PASS w=0",
              ev and ev["outcome"] == "pass" and ev["weight"] == 0.0,
              json.dumps(ev)[:200] if ev else "missing")
    for path, page in sorted(by_path.items()):
        if path == "/":
            continue
        code, detail = api.get(f"/site-crawls/{crawl_id}/pages/{page['site_url_id']}")
        evals = {ev["rule_id"]: ev for ev in detail["evaluations"]}
        for rule_id in SITE_ROOT_RULES:
            got = evals.get(rule_id)
            check(f"{path} {rule_id} not_applicable (not anchored here)",
                  got is not None and got["outcome"] == "not_applicable",
                  f"got {got and got['outcome']}")

    print("== B7: crawl_finalize rows post-finalize (Free)")
    for path, page in sorted(by_path.items()):
        code, detail = api.get(f"/site-crawls/{crawl_id}/pages/{page['site_url_id']}")
        evals = {ev["rule_id"]: ev for ev in detail["evaluations"]}
        bil = evals.get("technical.broken_internal_link")
        check(f"{path} broken_internal_link PASS (all targets reachable)",
              bil is not None and bil["outcome"] == "pass",
              json.dumps(bil)[:200] if bil else "missing")
        if bil:
            check(f"{path} broken_internal_link checked_count>0",
                  (bil["evidence"] or {}).get("checked_count", 0) > 0,
                  json.dumps(bil["evidence"])[:150])
        href = evals.get("technical.hreflang_conflict")
        check(f"{path} hreflang_conflict N/A (no hreflang in fixture)",
              href is not None and href["outcome"] == "not_applicable",
              json.dumps(href)[:150] if href else "missing")
        so = evals.get("technical.sitemap_orphan")
        if path == "/":
            check("root sitemap_orphan N/A no_sitemap (Free skips ingestion)",
                  so is not None and so["outcome"] == "not_applicable"
                  and (so["evidence"] or {}).get("reason") == "no_sitemap",
                  json.dumps(so)[:200] if so else "missing")
        else:
            check(f"{path} sitemap_orphan row absent (root-anchored only)",
                  so is None, "unexpected row present")

    print("== B6: grouped issues")
    code, issues_page = api.get(f"/site-crawls/{crawl_id}/issues?limit=100")
    assert code == 200, f"issues: {code}"
    issues = issues_page["items"]
    by_rule = {i["rule_id"]: i for i in issues}
    expected_issue_rules = {
        "technical.ai_crawler_access": ("high", "technical",
                                        "AI crawlers blocked by robots.txt"),
        "aeo.author_present": ("medium", "aeo", "Missing author byline"),
        "aeo.date_present": ("medium", "aeo", "Missing published/modified date"),
        "aeo.schema_expected_for_type": ("high", "aeo",
                                         "Missing expected schema type for page type"),
        "aeo.schema_matches_content": ("medium", "aeo",
                                       "Schema markup does not match visible content"),
        "aeo.schema_recommended_present": ("low", "aeo",
                                           "Recommended schema properties missing"),
        "aeo.answer_first": ("medium", "aeo", "No answer-first content structure"),
        "aeo.outbound_citations": ("low", "aeo", "No outbound citations"),
        "technical.hsts_present": ("low", "technical", "Missing HSTS header"),
        "technical.uncompressed_html": ("low", "technical", "HTML served uncompressed"),
        "technical.title_length_band": ("low", "technical",
                                        "Title length outside recommended band"),
        "technical.meta_description_length_band": (
            "low", "technical", "Meta description length outside recommended band"),
        "technical.canonical_present": ("medium", "technical", "Missing canonical URL"),
    }
    for rule_id, (sev, dim, title) in expected_issue_rules.items():
        issue = by_rule.get(rule_id)
        check(f"issue {rule_id} present", issue is not None)
        if issue:
            check(f"issue {rule_id} severity={sev}", issue["severity"] == sev,
                  issue["severity"])
            check(f"issue {rule_id} dimension={dim}", issue["dimension"] == dim,
                  issue["dimension"])
            check(f"issue {rule_id} display label", issue["title"] == title,
                  issue["title"])
    # Weight-0 ai_crawler_access fail still becomes an issue (weight only
    # excludes scoring, never issue projection).
    ai = by_rule.get("technical.ai_crawler_access")
    if ai:
        check("ai_crawler_access affects exactly the root",
              ai["affected_url_count"] == 1, str(ai["affected_url_count"]))
        code, detail = api.get(f"/site-crawls/{crawl_id}/issues/{ai['id']}")
        if code == 200:
            urls = detail.get("affected_urls") or []
            check("ai_crawler_access affected url is root with page_type",
                  len(urls) == 1 and urls[0]["normalized_url"].rstrip("/")
                  == FIXTURE_URL.rstrip("/") and urls[0]["page_type"] == "homepage",
                  json.dumps(urls)[:250])
    summary_counts = issues_page["summary"]["severity_counts"]
    check("issue summary counts consistent",
          sum(summary_counts.get(s, 0) for s in ("critical", "high", "medium", "low"))
          == issues_page["summary"]["issue_count"],
          json.dumps(issues_page["summary"]))
    # page_type filter on the issues LIST endpoint: groups narrow to the
    # matching type (spec §5.6 scopes the filter to list endpoints; the group
    # DETAIL endpoint is deliberately filter-independent — it always shows the
    # rule's full affected set, which is not a bug).
    code, filtered = api.get(f"/site-crawls/{crawl_id}/issues?page_type=other&limit=50")
    check("issues page_type=other filter works", code == 200,
          f"code={code}")
    if code == 200:
        items = filtered["items"]
        check("page_type=other narrows every group to the 1 'other' page",
              bool(items) and all(i["affected_url_count"] == 1 for i in items),
              json.dumps([(i["rule_id"], i["affected_url_count"]) for i in items]))
        check("page_type=other summary affected_url_count == 1",
              filtered["summary"]["affected_url_count"] == 1,
              str(filtered["summary"]["affected_url_count"]))
        # /misc/plain/ is the only 'other' page: schema_expected_for_type
        # (high, no JSON-LD) must be in the narrowed set; ai_crawler_access
        # (root=homepage) must NOT be.
        narrowed = {i["rule_id"] for i in items}
        check("narrowed set contains schema_expected_for_type",
              "aeo.schema_expected_for_type" in narrowed, json.dumps(sorted(narrowed)))
        check("narrowed set excludes root-only ai_crawler_access",
              "technical.ai_crawler_access" not in narrowed, json.dumps(sorted(narrowed)))
        # Document the group-detail contract: full affected set, unfiltered.
        target = next((i for i in items if i["rule_id"] == "aeo.author_present"), None)
        if target:
            c2, d2 = api.get(f"/site-crawls/{crawl_id}/issues/{target['id']}")
            check("group detail is filter-independent (full 8-url set)",
                  c2 == 200 and d2["affected_url_count"] == 8,
                  f"code={c2} count={d2.get('affected_url_count')}")

    print("== B8: exports (all three views; rule ids live in view=issues)")
    for fmt in ("csv", "md"):
        for view in ("inventory", "pages", "issues"):
            code, body = api.req(
                "GET", f"/site-crawls/{crawl_id}/export.{fmt}?view={view}", raw=True)
            check(f"export.{fmt}?view={view} 200", code == 200, f"code={code}")
            if code != 200:
                continue
            text = body.decode("utf-8", "replace")
            check(f"export.{fmt}?view={view} carries page_type", "page_type" in text)
            if view == "issues":
                check(f"export.{fmt}?view=issues carries P2 rule ids",
                      "technical.ai_crawler_access" in text
                      and "aeo.schema_expected_for_type" in text
                      and "aeo.answer_first" in text
                      and "technical.hsts_present" in text)
                check(f"export.{fmt}?view=issues carries display labels",
                      "AI crawlers blocked by robots.txt" in text)
            if view == "inventory":
                check(f"export.{fmt}?view=inventory carries scores + types",
                      "homepage" in text and "77.3" in text)
        code, body = api.req("GET", f"/site-crawls/{crawl_id}/export.{fmt}?view=bogus",
                             raw=True)
        check(f"export.{fmt}?view=bogus rejected 422", code == 422, f"code={code}")

    print("== B9: dashboard")
    code, dash = api.get(f"/projects/{project_id}/site-health")
    check("dashboard 200", code == 200, f"code={code}")
    if code == 200:
        ss = dash.get("score_summary") or {}
        check("dashboard score_summary present", bool(ss))
        by_type = ss.get("by_page_type") or {}
        check("by_page_type has all 9 types",
              set(by_type.keys()) == set(PATH_TYPES.values()),
              json.dumps(sorted(by_type.keys())))
        check("dashboard crawl.site_facts present",
              bool((dash.get("crawl") or {}).get("site_facts")))
        check("analyzed_count 9 in summary", ss.get("analyzed_count") == 9,
              str(ss.get("analyzed_count")))

    return summary("Suite B (Free crawl)")


if __name__ == "__main__":
    sys.exit(main())
