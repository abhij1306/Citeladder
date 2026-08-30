from types import SimpleNamespace
from uuid import uuid4

from app.domain.site_health.issue_snapshot import _rollup


def _issue(
    *,
    rule_id: str,
    finding_class: str,
    severity: str,
    score_roles: list[str],
    site_url_id=None,
    scope: str = "page",
):
    return SimpleNamespace(
        rule_id=rule_id,
        finding_class=finding_class,
        severity=severity,
        score_roles=score_roles,
        scope=scope,
        site_url_id=site_url_id or uuid4(),
        category="content",
        description=rule_id,
        remediation="Fix it.",
    )


def test_issue_snapshot_separates_card_counts_and_readiness_impact() -> None:
    shared_page = uuid4()
    rows = [
        _issue(
            rule_id="technical.title_present",
            finding_class="defect",
            severity="high",
            score_roles=["web_fundamentals"],
            site_url_id=shared_page,
        ),
        _issue(
            rule_id="aeo.editorial_lead_present",
            finding_class="advisory",
            severity="critical",
            score_roles=["aeo_readiness"],
            site_url_id=shared_page,
        ),
        _issue(
            rule_id="technical.indexable",
            finding_class="defect",
            severity="critical",
            score_roles=["web_fundamentals", "aeo_readiness"],
        ),
        _issue(
            rule_id="technical.meta_description_present",
            finding_class="advisory",
            severity="critical",
            score_roles=[],
        ),
        _issue(
            rule_id="aeo.organization_identity",
            finding_class="advisory",
            severity="high",
            score_roles=["aeo_readiness"],
            scope="site",
        ),
    ]

    projection = _rollup(rows)

    assert projection.issue_count == 5
    assert projection.technical_defect_count == 2
    assert projection.technical_defect_affected_page_count == 2
    assert projection.aeo_readiness_gap_count == 3
    assert projection.aeo_readiness_gap_affected_page_count == 2
    by_rule = {item["rule_id"]: item for item in projection.top_issues}
    assert by_rule["technical.title_present"]["impact_label"] == "High"
    assert by_rule["technical.title_present"]["impact_band"] == 3
    assert by_rule["aeo.editorial_lead_present"]["impact_label"] == (
        "Answerability · 20%"
    )
    assert by_rule["aeo.editorial_lead_present"]["impact_band"] == 2
    assert by_rule["technical.meta_description_present"]["impact_label"] == ("Advisory")
    assert by_rule["technical.meta_description_present"]["impact_band"] == 0
