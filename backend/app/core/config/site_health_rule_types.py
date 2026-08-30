"""Value types and classification policy shared by Site Health rule catalogs."""

from __future__ import annotations

from typing import Final

FINDING_CLASS_DEFECT: Final = "defect"
FINDING_CLASS_ADVISORY: Final = "advisory"
FINDING_CLASS_DIAGNOSTIC: Final = "diagnostic"
FINDING_CLASSES: Final[frozenset[str]] = frozenset(
    {FINDING_CLASS_DEFECT, FINDING_CLASS_ADVISORY, FINDING_CLASS_DIAGNOSTIC}
)

# Expectations rely on the page-kind classification. Triggered rules validate
# an artifact already observed on the page and therefore do not.
KIND_EVIDENCE_EXPECTATION: Final = "expectation"
KIND_EVIDENCE_TRIGGERED: Final = "triggered"
KIND_EVIDENCE_CLASSES: Final[frozenset[str]] = frozenset(
    {KIND_EVIDENCE_EXPECTATION, KIND_EVIDENCE_TRIGGERED}
)


class SiteHealthRule:
    """One immutable, config-owned Site Health rule definition."""

    __slots__ = (
        "applicability_key",
        "category",
        "description",
        "dimension",
        "display_label",
        "display_label_variants",
        "finding_class",
        "kind_evidence",
        "remediation",
        "rule_id",
        "rule_version",
        "score_roles",
        "severity",
        "web_fundamentals_area",
        "weight",
    )

    def __init__(
        self,
        *,
        rule_id: str,
        rule_version: str,
        dimension: str,
        category: str,
        severity: str,
        weight: float,
        applicability_key: str,
        description: str,
        remediation: str,
        display_label: str = "",
        display_label_variants: dict[str, str] | None = None,
        finding_class: str = FINDING_CLASS_DEFECT,
        kind_evidence: str = KIND_EVIDENCE_EXPECTATION,
        score_roles: tuple[str, ...] = (),
        web_fundamentals_area: str = "",
    ) -> None:
        if finding_class not in FINDING_CLASSES:
            raise ValueError(f"Unsupported finding class: {finding_class}")
        if kind_evidence not in KIND_EVIDENCE_CLASSES:
            raise ValueError(f"Unsupported kind evidence: {kind_evidence}")
        self.rule_id = rule_id
        self.rule_version = rule_version
        self.dimension = dimension
        self.category = category
        self.severity = severity
        self.finding_class = finding_class
        self.kind_evidence = kind_evidence
        self.score_roles = tuple(score_roles)
        self.web_fundamentals_area = web_fundamentals_area
        self.weight = weight
        self.applicability_key = applicability_key
        self.description = description
        self.remediation = remediation
        self.display_label = display_label or rule_id
        self.display_label_variants = dict(display_label_variants or {})
