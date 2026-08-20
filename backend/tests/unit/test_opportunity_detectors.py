"""Opportunities detectors: table-driven per-rule firing + edge cases."""

from __future__ import annotations

import uuid

import pytest

from app.analysis.opportunities.detectors import (
    AnalysisEvidence,
    CommerceEvidence,
    ProductAttributeGapEvidence,
    ProductEntryEvidence,
    PromptSnapshotEvidence,
    SiteEvidence,
    SiteIssueEvidence,
    SiteUrlEvidence,
    VisibilityEvidence,
    detect_brand_absent_high_value_prompt,
    detect_competitor_product_dominates,
    detect_owned_page_not_cited,
    detect_price_mention_mismatch,
    detect_product_attribute_gap,
    detect_product_not_mentioned,
    detect_site_issue_opportunities,
)
from app.analysis.opportunities.source_patterns import CitationEvidence
from app.core.config.opportunities import (
    COMMERCE_COMPETITOR_SOV_THRESHOLD,
    COMMERCE_GAP_FACTOR,
    COMMERCE_PRICE_MISMATCH_RATE_THRESHOLD,
    COMMERCE_VALUE_FACTOR,
    OPPORTUNITY_RULES_BY_ID,
    SITE_GAP_FACTOR,
    SITE_VALUE_FACTOR,
)


def _analysis(
    prompt_index: int,
    *,
    owned: int = 0,
    competitors: tuple[str, ...] = (),
    engine: str = "gemini",
    citations: tuple[CitationEvidence, ...] = (),
) -> AnalysisEvidence:
    return AnalysisEvidence(
        analysis_id=uuid.uuid4(),
        prompt_index=prompt_index,
        logical_engine=engine,
        owned_citation_count=owned,
        competitor_names=competitors,
        citations=citations,
    )


def _citation(domain: str, *, competitor: str | None = None) -> CitationEvidence:
    return CitationEvidence(
        domain=domain,
        url=f"https://{domain}/page",
        title=domain,
        is_owned=False,
        matched_competitor=competitor,
    )


def _snapshot(
    prompt_index: int,
    *,
    prompt_id: uuid.UUID | None = None,
    text: str = "best payroll software",
    theme: str = "payroll",
    intent: str = "comparison",
) -> PromptSnapshotEvidence:
    return PromptSnapshotEvidence(
        prompt_index=prompt_index,
        prompt_id=prompt_id if prompt_id is not None else uuid.uuid4(),
        text=text,
        theme=theme,
        intent=intent,
    )


def _visibility(
    analyses: tuple[AnalysisEvidence, ...],
    snapshots: tuple[PromptSnapshotEvidence, ...] = (),
    owned_domains: tuple[str, ...] = ("acme.com",),
) -> VisibilityEvidence:
    return VisibilityEvidence(
        audit_id=uuid.uuid4(),
        analyses=analyses,
        prompt_snapshots=snapshots,
        owned_domains=owned_domains,
    )


# =========================================================================
# brand_absent_high_value_prompt
# =========================================================================
def test_brand_absent_fires_without_owned_and_with_competitor() -> None:
    evidence = _visibility(
        (
            _analysis(0, competitors=("Globex",)),
            _analysis(0, competitors=("Globex", "Initech"), engine="chatgpt"),
        ),
        (_snapshot(0),),
    )
    hits = detect_brand_absent_high_value_prompt(evidence)
    assert len(hits) == 1
    hit = hits[0]
    assert hit.rule_id == "brand_absent_high_value_prompt"
    assert hit.evidence["repetitions"] == 2
    assert hit.evidence["competitor_names"] == ["Globex", "Initech"]
    assert hit.evidence["engines"] == ["chatgpt", "gemini"]
    assert hit.evidence["prompt_text"] == "best payroll software"
    assert hit.evidence["prompt_intent"] == "comparison"
    assert hit.evidence["prompt_theme"] == "payroll"
    assert hit.value_factor > 1.0  # comparison intent is weighted above base
    assert hit.gap_factor > 1.0  # competitors present, zero owned rate
    assert len(hit.source_analysis_ids) == 2
    assert hit.source_issue_ids == ()


@pytest.mark.parametrize(
    "analyses",
    [
        # An owned citation in ANY repetition suppresses the rule.
        (_analysis(0, owned=1, competitors=("Globex",)), _analysis(0)),
        # No competitor citation-or-mention anywhere -> no gap to close.
        (_analysis(0), _analysis(0, engine="chatgpt")),
    ],
)
def test_brand_absent_does_not_fire(analyses: tuple[AnalysisEvidence, ...]) -> None:
    evidence = _visibility(analyses, (_snapshot(0),))
    assert detect_brand_absent_high_value_prompt(evidence) == []


def test_brand_absent_empty_evidence_yields_no_hits() -> None:
    assert detect_brand_absent_high_value_prompt(_visibility(())) == []


def test_brand_absent_target_key_prefers_prompt_id() -> None:
    prompt_id = uuid.uuid4()
    evidence = _visibility(
        (_analysis(0, competitors=("Globex",)),),
        (_snapshot(0, prompt_id=prompt_id),),
    )
    (hit,) = detect_brand_absent_high_value_prompt(evidence)
    assert hit.target_key == f"prompt:{prompt_id}"
    assert hit.target_prompt_id == prompt_id
    assert hit.target_theme == "payroll"


def test_brand_absent_target_key_falls_back_to_prompt_index() -> None:
    evidence = _visibility(
        (_analysis(3, competitors=("Globex",)),),
        (_snapshot(3, prompt_id=None),),
    )
    # ``_snapshot`` mints an id when not told otherwise; force the null link.
    snapshots = (
        PromptSnapshotEvidence(
            prompt_index=3, prompt_id=None, text="t", theme="", intent=""
        ),
    )
    evidence = _visibility((_analysis(3, competitors=("Globex",)),), snapshots)
    (hit,) = detect_brand_absent_high_value_prompt(evidence)
    assert hit.target_key == f"prompt-index:{evidence.audit_id}:3"
    assert hit.target_prompt_id is None
    assert hit.target_theme is None
    # Unknown/empty intent -> default value factor.
    assert hit.value_factor == 1.0


def test_brand_absent_missing_snapshot_still_fires() -> None:
    evidence = _visibility((_analysis(1, competitors=("Globex",)),), ())
    (hit,) = detect_brand_absent_high_value_prompt(evidence)
    assert hit.target_key == f"prompt-index:{evidence.audit_id}:1"
    assert hit.evidence["prompt_text"] == ""
    assert hit.evidence["prompt_intent"] == ""


def test_brand_absent_groups_by_prompt_index() -> None:
    evidence = _visibility(
        (
            _analysis(0, competitors=("Globex",)),
            _analysis(1, competitors=("Initech",)),
            _analysis(2, owned=2, competitors=("Globex",)),
        ),
        (_snapshot(0), _snapshot(1), _snapshot(2)),
    )
    hits = detect_brand_absent_high_value_prompt(evidence)
    assert len(hits) == 2
    assert [h.evidence["prompt_index"] for h in hits] == [0, 1]


# =========================================================================
# Observed source pattern (descriptive evidence, never a firing input)
# =========================================================================
def test_gap_evidence_carries_the_observed_source_pattern() -> None:
    evidence = _visibility(
        (
            _analysis(
                0,
                competitors=("Globex",),
                citations=(
                    _citation("globex.com", competitor="Globex"),
                    _citation("g2.com"),
                ),
            ),
            _analysis(
                0,
                competitors=("Globex",),
                engine="chatgpt",
                # Same competitor domain again: one repeated domain, not two.
                citations=(
                    _citation("globex.com", competitor="Globex"),
                    _citation("reddit.com"),
                ),
            ),
        ),
        (_snapshot(0),),
    )
    (hit,) = detect_brand_absent_high_value_prompt(evidence)
    pattern = hit.evidence["source_pattern"]
    assert pattern["distinct_domain_count"] == 3
    assert pattern["class_counts"] == {
        "competitor_owned": 1,
        "review_marketplace": 1,
        "community": 1,
    }
    assert pattern["competitor_source_domains"] == {"Globex": ["globex.com"]}
    assert "competitor_owned_sources_cited" in pattern["observed_patterns"]
    assert "community_evidence_present" in pattern["observed_patterns"]


def test_owned_page_not_cited_also_carries_the_source_pattern() -> None:
    evidence = _visibility(
        (_analysis(0, citations=(_citation("youtube.com"),)),),
        (_snapshot(0),),
    )
    (hit,) = detect_owned_page_not_cited(evidence)
    assert hit.evidence["source_pattern"]["class_counts"] == {"video": 1}


def test_source_pattern_never_changes_whether_a_rule_fires() -> None:
    """A rich citation set cannot make a non-firing prompt fire, or vice versa."""
    # Brand IS cited -> suppressed no matter how many competitor sources exist.
    cited = _visibility(
        (
            _analysis(
                0,
                owned=1,
                competitors=("Globex",),
                citations=(_citation("globex.com", competitor="Globex"),),
            ),
        ),
        (_snapshot(0),),
    )
    assert detect_brand_absent_high_value_prompt(cited) == []

    # Competitor MENTIONED but nothing cited -> still fires, with a zeroed
    # pattern block rather than a missing one.
    uncited = _visibility((_analysis(0, competitors=("Globex",)),), (_snapshot(0),))
    (hit,) = detect_brand_absent_high_value_prompt(uncited)
    assert hit.evidence["source_pattern"]["distinct_domain_count"] == 0
    assert hit.evidence["source_pattern"]["observed_patterns"] == []


def test_source_pattern_abstains_on_unknown_domains() -> None:
    evidence = _visibility(
        (
            _analysis(
                0, competitors=("Globex",), citations=(_citation("obscure.example"),)
            ),
        ),
        (_snapshot(0),),
    )
    (hit,) = detect_brand_absent_high_value_prompt(evidence)
    assert hit.evidence["source_pattern"]["class_counts"] == {"other_third_party": 1}


# =========================================================================
# owned_page_not_cited
# =========================================================================
def test_owned_page_not_cited_fires_with_zero_owned_citations() -> None:
    evidence = _visibility((_analysis(0),), (_snapshot(0),))
    hits = detect_owned_page_not_cited(evidence)
    assert len(hits) == 1
    hit = hits[0]
    assert hit.rule_id == "owned_page_not_cited"
    assert hit.evidence["owned_domains"] == ["acme.com"]
    assert hit.evidence["repetitions"] == 1
    assert hit.evidence["owned_citation_count"] == 0
    assert len(hit.source_analysis_ids) == 1


def test_owned_page_not_cited_skipped_without_owned_domains() -> None:
    evidence = _visibility((_analysis(0),), (_snapshot(0),), owned_domains=())
    assert detect_owned_page_not_cited(evidence) == []


def test_owned_page_not_cited_suppressed_by_any_owned_citation() -> None:
    evidence = _visibility(
        (_analysis(0), _analysis(0, owned=1, engine="chatgpt")),
        (_snapshot(0),),
    )
    assert detect_owned_page_not_cited(evidence) == []


def test_owned_page_not_cited_empty_evidence_yields_no_hits() -> None:
    assert detect_owned_page_not_cited(_visibility(())) == []


# =========================================================================
# Site rules (missing_structured_data / thin_content)
# =========================================================================
def _site(
    issues: tuple[SiteIssueEvidence, ...],
    urls: tuple[SiteUrlEvidence, ...],
) -> SiteEvidence:
    return SiteEvidence(
        crawl_id=uuid.uuid4(),
        issues=issues,
        urls=urls,
        coverage={"crawl_status": "cancelled", "analysis_ratio": 0.5},
        limitations=("Site Health evidence is partial.",),
    )


def _issue(
    rule_id: str,
    site_url_id: uuid.UUID,
    *,
    severity: str = "medium",
    category: str = "structured_data",
    finding_class: str = "defect",
) -> SiteIssueEvidence:
    return SiteIssueEvidence(
        issue_id=uuid.uuid4(),
        rule_id=rule_id,
        severity=severity,
        category=category,
        finding_class=finding_class,
        site_url_id=site_url_id,
        evidence={"detail": "x"},
    )


def _url(site_url_id: uuid.UUID, normalized_url: str) -> SiteUrlEvidence:
    return SiteUrlEvidence(site_url_id=site_url_id, normalized_url=normalized_url)


def test_site_rules_fire_from_mapped_issues() -> None:
    url_id = uuid.uuid4()
    evidence = _site(
        (
            _issue("aeo.structured_data_present", url_id),
            _issue(
                "technical.thin_content",
                url_id,
                severity="medium",
                category="content",
            ),
            _issue("aeo.open_graph_present", url_id),  # not mapped -> ignored
        ),
        (_url(url_id, "https://acme.com/pricing"),),
    )
    hits = detect_site_issue_opportunities(evidence)
    assert [h.rule_id for h in hits] == ["missing_structured_data", "thin_content"]
    for hit in hits:
        assert hit.target_key == "url:https://acme.com/pricing"
        assert hit.target_url == "https://acme.com/pricing"
        assert hit.target_prompt_id is None
        assert hit.value_factor == SITE_VALUE_FACTOR
        assert hit.gap_factor == SITE_GAP_FACTOR
        assert len(hit.source_issue_ids) == 1
        assert hit.source_analysis_ids == ()
        assert hit.evidence["crawl_id"] == str(evidence.crawl_id)
        assert hit.evidence["url"] == "https://acme.com/pricing"
        assert hit.evidence["issue_evidence"] == {"detail": "x"}
        assert hit.evidence["coverage"] == evidence.coverage
        assert hit.evidence["limitations"] == list(evidence.limitations)


def test_site_rules_skip_issue_with_unknown_url_identity() -> None:
    evidence = _site(
        (_issue("aeo.structured_data_present", uuid.uuid4()),),
        (),  # no URL map entries
    )
    assert detect_site_issue_opportunities(evidence) == []


def test_site_rules_never_project_advisories_as_opportunities() -> None:
    url_id = uuid.uuid4()
    evidence = _site(
        (
            _issue(
                "aeo.structured_data_present",
                url_id,
                finding_class="advisory",
            ),
        ),
        (_url(url_id, "https://acme.com/pricing"),),
    )
    assert detect_site_issue_opportunities(evidence) == []


def test_site_rules_empty_evidence_yields_no_hits() -> None:
    assert detect_site_issue_opportunities(_site((), ())) == []


def test_schema_type_mismatch_fires_from_mapped_issue() -> None:
    url_id = uuid.uuid4()
    evidence = _site(
        (_issue("aeo.schema_expected_for_type", url_id, severity="high"),),
        (_url(url_id, "https://acme.com/product"),),
    )
    (hit,) = detect_site_issue_opportunities(evidence)
    assert hit.rule_id == "schema_type_mismatch"
    assert hit.target_key == "url:https://acme.com/product"
    assert hit.target_url == "https://acme.com/product"
    assert hit.evidence["issue_rule_id"] == "aeo.schema_expected_for_type"
    assert hit.evidence["site_url_id"] == str(url_id)
    assert len(hit.source_issue_ids) == 1
    # Own remediation copy, not missing_structured_data's.
    rule = OPPORTUNITY_RULES_BY_ID["schema_type_mismatch"]
    missing = OPPORTUNITY_RULES_BY_ID["missing_structured_data"]
    assert rule.remediation != missing.remediation


# =========================================================================
# Commerce rules (ProductMetricSnapshot / frozen-catalog evidence)
# =========================================================================
# Sentinel distinguishing "no snapshot_id argument" from an explicit None.
_UNSET = object()


def _entry(
    entry_id: str,
    *,
    kind: str = "product",
    name: str = "Summit 40L",
    sku: str = "SUMMIT-40",
    competitor_name: str = "",
    mention_count: int = 0,
    sov_share: float = 0.0,
    price_mismatch_rate: float | None = None,
    # ``_UNSET`` (not None) is the "generate one" default, so a caller can pass
    # snapshot_id=None to build the never-measured entry the provenance rule
    # turns on. Defaulting None to a fresh UUID made that shape unreachable.
    snapshot_id: uuid.UUID | None | object = _UNSET,
    source_analysis_ids: tuple[str, ...] = (),
) -> ProductEntryEvidence:
    resolved_snapshot_id = uuid.uuid4() if snapshot_id is _UNSET else snapshot_id
    return ProductEntryEvidence(
        entry_id=entry_id,
        kind=kind,
        name=name,
        sku=sku,
        competitor_name=competitor_name,
        mention_count=mention_count,
        sov_share=sov_share,
        price_mismatch_rate=price_mismatch_rate,
        snapshot_id=resolved_snapshot_id,  # type: ignore[arg-type]
        source_analysis_ids=source_analysis_ids,
    )


def _commerce(entries: tuple[ProductEntryEvidence, ...]) -> CommerceEvidence:
    return CommerceEvidence(audit_id=uuid.uuid4(), entries=entries)


def test_product_not_mentioned_fires_on_zero_mentions() -> None:
    entry = _entry("p-zero", mention_count=0)
    evidence = _commerce(
        (
            _entry("p-mentioned", mention_count=3),
            entry,
            _entry(
                "c-zero",
                kind="competitor_product",
                name="TrailBlaze Alpine 45",
                mention_count=0,
            ),
        )
    )
    (hit,) = detect_product_not_mentioned(evidence)
    assert hit.rule_id == "product_not_mentioned"
    assert hit.target_key == "product:p-zero"
    assert hit.target_prompt_id is None
    assert hit.target_url is None
    assert hit.target_theme is None
    assert hit.evidence["product_name"] == "Summit 40L"
    assert hit.evidence["product_sku"] == "SUMMIT-40"
    assert hit.evidence["audit_id"] == str(evidence.audit_id)
    # Competitor products never fire the own-catalog rule.
    assert hit.target_key != "competitor-product:c-zero"


def test_product_attribute_gap_uses_persisted_comparison_provenance() -> None:
    metric_id = str(uuid.uuid4())
    evidence = CommerceEvidence(
        audit_id=uuid.uuid4(),
        entries=(),
        attribute_gaps=(
            ProductAttributeGapEvidence(
                product_id="p-gap",
                product_name="Summit 40L",
                product_sku="SUMMIT-40",
                competitor_name="TrailBlaze",
                gaps=({"field": "warranty", "competitor_value": "Lifetime"},),
                source_metric_ids=(metric_id,),
            ),
        ),
    )
    (hit,) = detect_product_attribute_gap(evidence)
    assert hit.rule_id == "product_attribute_gap"
    assert hit.target_key == "product:p-gap"
    assert hit.source_metric_ids == (metric_id,)
    assert hit.evidence["attribute_gaps"][0]["field"] == "warranty"


def test_product_not_mentioned_empty_evidence_yields_no_hits() -> None:
    assert detect_product_not_mentioned(_commerce(())) == []


def test_product_not_mentioned_skips_never_measured_entry() -> None:
    """No snapshot AND no source analyses -> no provenance, so no hit.

    A zero-filled snapshot exists for every entry the audit measured
    (invariant 7), so a bare entry means the audit never measured it — and
    emitting it would produce a DetectorHit with all three provenance lists
    empty, violating the invariant-4 contract.
    """
    evidence = _commerce((_entry("p-unmeasured", mention_count=0, snapshot_id=None),))
    assert detect_product_not_mentioned(evidence) == []


def test_product_not_mentioned_fires_when_only_analyses_carry_provenance() -> None:
    """A snapshot-less entry with source analyses still has provenance."""
    analysis_id = str(uuid.uuid4())
    evidence = _commerce(
        (
            _entry(
                "p-analyses-only",
                mention_count=0,
                snapshot_id=None,
                source_analysis_ids=(analysis_id,),
            ),
        )
    )
    (hit,) = detect_product_not_mentioned(evidence)
    assert hit.source_analysis_ids == (analysis_id,)
    assert hit.source_metric_ids == ()


def test_product_not_mentioned_hits_always_carry_provenance() -> None:
    """Every emitted hit populates at least one provenance list (invariant 4)."""
    evidence = _commerce(
        (
            _entry("p-measured", mention_count=0),
            _entry("p-unmeasured", mention_count=0, snapshot_id=None),
        )
    )
    hits = detect_product_not_mentioned(evidence)
    assert [hit.target_key for hit in hits] == ["product:p-measured"]
    for hit in hits:
        assert hit.source_analysis_ids or hit.source_issue_ids or hit.source_metric_ids


def test_competitor_product_dominates_fires_above_threshold() -> None:
    entry = _entry(
        "c-dom",
        kind="competitor_product",
        name="TrailBlaze Alpine 45",
        competitor_name="TrailBlaze",
        mention_count=9,
        sov_share=COMMERCE_COMPETITOR_SOV_THRESHOLD + 0.1,
        source_analysis_ids=(str(uuid.uuid4()),),
    )
    evidence = _commerce(
        (
            entry,
            _entry("p-own", mention_count=1, sov_share=0.1),
            # Below/at the threshold -> no firing.
            _entry(
                "c-tie",
                kind="competitor_product",
                name="Tie",
                sov_share=COMMERCE_COMPETITOR_SOV_THRESHOLD,
            ),
        )
    )
    (hit,) = detect_competitor_product_dominates(evidence)
    assert hit.rule_id == "competitor_product_dominates"
    assert hit.target_key == "competitor-product:c-dom"
    assert hit.evidence["competitor_name"] == "TrailBlaze"
    assert hit.evidence["sov_share"] == entry.sov_share
    assert hit.evidence["sov_threshold"] == COMMERCE_COMPETITOR_SOV_THRESHOLD
    assert hit.source_analysis_ids == entry.source_analysis_ids
    assert hit.source_metric_ids == (str(entry.snapshot_id),)
    assert hit.value_factor == COMMERCE_VALUE_FACTOR
    assert hit.gap_factor == COMMERCE_GAP_FACTOR


def test_price_mention_mismatch_fires_above_threshold() -> None:
    entry = _entry(
        "p-mismatch",
        mention_count=4,
        price_mismatch_rate=COMMERCE_PRICE_MISMATCH_RATE_THRESHOLD + 0.05,
    )
    evidence = _commerce(
        (
            entry,
            # Null rate (no verifiable prices) and at-threshold -> no firing.
            _entry("p-null", mention_count=2, price_mismatch_rate=None),
            _entry(
                "p-edge",
                mention_count=2,
                price_mismatch_rate=COMMERCE_PRICE_MISMATCH_RATE_THRESHOLD,
            ),
        )
    )
    (hit,) = detect_price_mention_mismatch(evidence)
    assert hit.rule_id == "price_mention_mismatch"
    assert hit.target_key == "product:p-mismatch"
    assert hit.evidence["price_mismatch_rate"] == entry.price_mismatch_rate
    assert (
        hit.evidence["price_mismatch_threshold"]
        == COMMERCE_PRICE_MISMATCH_RATE_THRESHOLD
    )
    assert hit.source_metric_ids == (str(entry.snapshot_id),)


@pytest.mark.parametrize(
    "rule_id,detector,evidence",
    [
        (
            "product_not_mentioned",
            detect_product_not_mentioned,
            _commerce((_entry("p-zero", mention_count=0),)),
        ),
        (
            "competitor_product_dominates",
            detect_competitor_product_dominates,
            _commerce(
                (
                    _entry(
                        "c-dom",
                        kind="competitor_product",
                        sov_share=COMMERCE_COMPETITOR_SOV_THRESHOLD + 0.1,
                    ),
                )
            ),
        ),
        (
            "price_mention_mismatch",
            detect_price_mention_mismatch,
            _commerce(
                (
                    _entry(
                        "p-mismatch",
                        price_mismatch_rate=COMMERCE_PRICE_MISMATCH_RATE_THRESHOLD
                        + 0.05,
                    ),
                )
            ),
        ),
        (
            "schema_type_mismatch",
            detect_site_issue_opportunities,
            (
                lambda url_id: _site(
                    (_issue("aeo.schema_expected_for_type", url_id),),
                    (_url(url_id, "https://acme.com/x"),),
                )
            )(uuid.uuid4()),
        ),
    ],
)
def test_disabled_new_rules_never_emit(
    monkeypatch, rule_id, detector, evidence
) -> None:
    rule = OPPORTUNITY_RULES_BY_ID[rule_id]
    assert detector(evidence), "sanity: the detector fires while enabled"
    monkeypatch.setattr(rule, "enabled", False)
    assert detector(evidence) == []


# =========================================================================
# Disabled rules are never emitted
# =========================================================================
@pytest.mark.parametrize(
    "rule_id,detector,evidence",
    [
        (
            "brand_absent_high_value_prompt",
            detect_brand_absent_high_value_prompt,
            _visibility((_analysis(0, competitors=("Globex",)),), (_snapshot(0),)),
        ),
        (
            "owned_page_not_cited",
            detect_owned_page_not_cited,
            _visibility((_analysis(0),), (_snapshot(0),)),
        ),
        (
            "missing_structured_data",
            detect_site_issue_opportunities,
            (
                lambda url_id: _site(
                    (_issue("aeo.structured_data_present", url_id),),
                    (_url(url_id, "https://acme.com/x"),),
                )
            )(uuid.uuid4()),
        ),
        (
            "thin_content",
            detect_site_issue_opportunities,
            (
                lambda url_id: _site(
                    (_issue("technical.thin_content", url_id, category="content"),),
                    (_url(url_id, "https://acme.com/x"),),
                )
            )(uuid.uuid4()),
        ),
    ],
)
def test_disabled_rules_never_emit(monkeypatch, rule_id, detector, evidence) -> None:
    rule = OPPORTUNITY_RULES_BY_ID[rule_id]
    assert detector(evidence), "sanity: the detector fires while enabled"
    monkeypatch.setattr(rule, "enabled", False)
    assert detector(evidence) == []
