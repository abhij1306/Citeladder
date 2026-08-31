import json

import pytest

from scripts.audit_site_health_50 import (
    _freeze_response,
    _load_independent_reviews,
    _read_existing_fixture,
    _redact_evidence,
    _validate_review_coverage,
    select_rows,
)
from scripts.site_health_audit_reporting import _rule_table_lines


def test_select_rows_freezes_twelve_per_company_plus_two_global() -> None:
    rows = [
        {
            "company": company,
            "url": f"https://{company.replace(' ', '-')}.test/{index}",
            "page_kind": ("product", "article", "category")[index % 3],
            "web_score": float(index),
            "aeo_score": float(20 - index),
        }
        for company in ("goodee", "lootcrate", "potgang", "united by blue")
        for index in range(14)
    ]

    selected = select_rows(rows)

    assert len(selected) == 50
    assert len({row["url"] for row in selected}) == 50
    counts = {
        company: sum(row["company"] == company for row in selected)
        for company in ("goodee", "lootcrate", "potgang", "united by blue")
    }
    assert all(count >= 12 for count in counts.values())
    assert sum(count - 12 for count in counts.values()) == 2


def test_independent_reviews_require_binary_unique_occurrence_rows(tmp_path) -> None:
    (tmp_path / "review-one.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "occurrence_id": "one",
                        "verdict": "verified",
                        "exact_observation": "H1 → H3, primary content",
                        "confidence": "high",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _load_independent_reviews(tmp_path) == {
        "one": {
            "verdict": "verified",
            "observation": "H1 → H3, primary content",
            "confidence": "high",
        }
    }

    (tmp_path / "review-two.json").write_text(
        json.dumps({"rows": [{"occurrence_id": "one", "verdict": "wrong"}]}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="duplicate review"):
        _load_independent_reviews(tmp_path)


def test_committed_evidence_redaction_is_bounded() -> None:
    redacted = _redact_evidence(
        {
            "safe": "x" * 800,
            "raw_html": "<button>secret</button>",
            "nested": [{"selector": "body > form", "count": 2}],
        }
    )

    assert redacted["safe"] == "x" * 400
    assert "raw_html" not in redacted
    assert redacted["nested"] == [{"count": 2}]


def test_frozen_response_round_trips_acquisition_metadata(tmp_path) -> None:
    response = {
        "body": b"<html></html>",
        "headers": {"content-type": "text/html; charset=utf-8"},
        "final_url": "https://example.com/final",
        "status_code": 203,
        "content_type": "text/html",
        "charset": "utf-8",
    }
    _freeze_response(tmp_path, "001.html", "001.headers.json", response)

    restored = _read_existing_fixture(
        tmp_path / "001.html",
        tmp_path / "001.headers.json",
        tmp_path / "001.meta.json",
    )

    assert restored is not None
    assert {key: restored[key] for key in response} == response


def test_existing_fixture_requires_metadata_sidecar(tmp_path) -> None:
    (tmp_path / "001.html").write_bytes(b"<html></html>")
    (tmp_path / "001.headers.json").write_text("{}", encoding="utf-8")

    assert (
        _read_existing_fixture(
            tmp_path / "001.html",
            tmp_path / "001.headers.json",
            tmp_path / "001.meta.json",
        )
        is None
    )


def test_review_coverage_compares_exact_occurrence_ids() -> None:
    manifest = [{"url": "https://example.com"}]
    issues = {"https://example.com": [{"occurrence_id": "expected"}]}

    with pytest.raises(RuntimeError, match=r"missing.*expected.*unexpected.*other"):
        _validate_review_coverage({"other": {}}, manifest, issues)


def test_rule_table_includes_replay_only_rules_without_mutating_counts() -> None:
    per_rule = {"reported.rule": {"verified": 1, "wrong": 0}}

    lines = _rule_table_lines(per_rule, [{"rule_id": "replay.only"}])

    assert any("`replay.only` | 0 | 0 | 0 | 1" in line for line in lines)
    assert per_rule == {"reported.rule": {"verified": 1, "wrong": 0}}
