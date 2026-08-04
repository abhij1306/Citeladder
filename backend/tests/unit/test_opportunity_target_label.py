"""Opportunities target_label: backend-owned target presentation (C1).

The label is derived from PERSISTED fields only — no prompt join — so a
prompt deleted after detection still yields its frozen snapshot text.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from app.core.config.opportunities import FORMULA_VERSION
from app.domain.opportunities.service import _humanize_theme, _project_item
from app.models.opportunity import Opportunity


def _row(
    *,
    target_url: str | None = None,
    target_theme: str | None = None,
    target_prompt_id: uuid.UUID | None = None,
    evidence: dict | None = None,
) -> Opportunity:
    return cast(
        Opportunity,
        SimpleNamespace(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            rule_id="brand_absent_high_value_prompt",
            opportunity_type="visibility",
            severity="high",
            priority_score=120.0,
            title="Brand absent on high-value prompt",
            target_key="prompt:xyz",
            target_prompt_id=target_prompt_id,
            target_url=target_url,
            target_theme=target_theme,
            evidence=evidence,
            status="open",
            formula_version=FORMULA_VERSION,
            source_analysis_ids=[],
            source_issue_ids=[],
            source_metric_ids=[],
            source_traffic_ids=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    )


def test_url_target_labels_with_the_url() -> None:
    item = _project_item(_row(target_url="https://acme.test/a"))
    assert item["target_label"] == "https://acme.test/a"


def test_prompt_target_labels_with_frozen_prompt_text() -> None:
    # The prompt row was deleted after detection (target_prompt_id null):
    # the frozen evidence snapshot still produces the label — no join.
    item = _project_item(
        _row(
            target_prompt_id=None,
            target_theme="crm",
            evidence={"prompt_text": "best crm for small teams"},
        )
    )
    assert item["target_label"] == "best crm for small teams"


def test_prompt_text_wins_over_theme() -> None:
    item = _project_item(
        _row(
            target_theme="crm",
            evidence={"prompt_text": "what is a crm"},
        )
    )
    assert item["target_label"] == "what is a crm"


def test_theme_target_is_humanized() -> None:
    item = _project_item(
        _row(target_theme="crm-software_tools", evidence={"prompt_text": "  "})
    )
    assert item["target_label"] == "Crm software tools theme"


def test_commerce_target_labels_with_frozen_product_name() -> None:
    item = _project_item(
        _row(evidence={"product_name": "Summit 40L", "mention_count": 0})
    )
    assert item["target_label"] == "Summit 40L"


def test_no_user_facing_target_yields_none() -> None:
    # Never falls back to the deterministic target_key.
    item = _project_item(_row(evidence={}))
    assert item["target_label"] is None
    item = _project_item(_row(evidence=None))
    assert item["target_label"] is None


def test_humanize_theme_edges() -> None:
    assert _humanize_theme("") == ""
    assert _humanize_theme("   ") == ""
    assert _humanize_theme("crm") == "Crm theme"
    assert _humanize_theme("-odd--tokens_") == "Odd tokens theme"
