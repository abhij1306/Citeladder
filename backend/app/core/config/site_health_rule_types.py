"""Value types and classification policy shared by Site Health rule catalogs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from app.core.config.site_health_contracts import (
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_SATISFIED,
)

SCORE_ROLE_WEB_FUNDAMENTALS: Final = "web_fundamentals"
SCORE_ROLE_AEO: Final = "aeo_readiness"

# Evidence ownership is separate from applicability. A site rule may persist
# on the root analysis; a graph rule persists on an architecture projection.
RULE_SCOPE_PAGE: Final = "page"
RULE_SCOPE_SITE: Final = "site"
RULE_SCOPE_CLUSTER: Final = "cluster"
RULE_SCOPE_GRAPH: Final = "graph"
RULE_SCOPES: Final[frozenset[str]] = frozenset(
    {RULE_SCOPE_PAGE, RULE_SCOPE_SITE, RULE_SCOPE_CLUSTER, RULE_SCOPE_GRAPH}
)

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

COMPOSITE_THRESHOLD_ALL_REQUIRED: Final = "all_required"
COMPOSITE_THRESHOLD_ALL_REQUIRED_AND_APPLICABLE: Final = "all_required_and_applicable"
COMPOSITE_THRESHOLDS: Final[frozenset[str]] = frozenset(
    {
        COMPOSITE_THRESHOLD_ALL_REQUIRED,
        COMPOSITE_THRESHOLD_ALL_REQUIRED_AND_APPLICABLE,
    }
)
COMPOSITE_CONDITION_PAGE_TRAIT: Final = "page_trait:"
COMPOSITE_CONDITION_NOT_PAGE_TRAIT: Final = "not_page_trait:"


class CompositeAtom:
    """One immutable atom in a bounded composite readiness contract."""

    __slots__ = ("condition", "name", "required")

    def __init__(self, *, name: str, required: bool, condition: str = "") -> None:
        normalized_name = name.strip()
        normalized_condition = condition.strip()
        if not normalized_name:
            raise ValueError("Composite atom requires a name")
        if normalized_condition and not normalized_condition.startswith(
            (COMPOSITE_CONDITION_PAGE_TRAIT, COMPOSITE_CONDITION_NOT_PAGE_TRAIT)
        ):
            raise ValueError(f"Unsupported composite atom condition: {condition}")
        if normalized_condition and normalized_condition.split(":", 1)[-1] == "":
            raise ValueError("Composite atom condition requires a trait")
        self.name = normalized_name
        self.required = required
        self.condition = normalized_condition

    def applies(self, page_traits: Iterable[str]) -> bool:
        """Resolve the atom from independently observed structural traits only."""
        traits = {str(trait) for trait in page_traits}
        if not self.condition:
            return True
        prefix, trait = self.condition.split(":", 1)
        return trait in traits if prefix == "page_trait" else trait not in traits


class CompositeContract:
    """Config-owned atom set and threshold for one composite rule."""

    __slots__ = ("atoms", "threshold")

    def __init__(self, *, atoms: tuple[CompositeAtom, ...], threshold: str) -> None:
        if not atoms:
            raise ValueError("Composite contract requires atoms")
        if threshold not in COMPOSITE_THRESHOLDS:
            raise ValueError(f"Unsupported composite threshold: {threshold}")
        names = [atom.name for atom in atoms]
        if len(names) != len(set(names)):
            raise ValueError("Composite contract atom names must be unique")
        self.atoms = atoms
        self.threshold = threshold

    def atom_detail(
        self,
        name: str,
        *,
        satisfied: bool,
        evidence: Any,
        page_traits: Iterable[str],
    ) -> dict[str, Any]:
        """Build persisted atom evidence under this contract's applicability."""
        atom = next((item for item in self.atoms if item.name == name), None)
        if atom is None:
            raise ValueError(f"Composite atom is not configured: {name}")
        applies = atom.applies(page_traits)
        if not applies:
            outcome = RULE_OUTCOME_NOT_APPLICABLE
        elif satisfied:
            outcome = RULE_OUTCOME_SATISFIED
        else:
            outcome = RULE_OUTCOME_MISSING
        return {
            "name": atom.name,
            "outcome": outcome,
            "required": atom.required,
            "condition": atom.condition,
            "evidence": evidence,
        }

    def outcome_for(self, atoms: Iterable[Mapping[str, object]]) -> str:
        """Return the discrete outcome from configured atom requirements."""
        applicable = [
            atom for atom in atoms if atom.get("outcome") != RULE_OUTCOME_NOT_APPLICABLE
        ]
        if not applicable:
            return RULE_OUTCOME_NOT_APPLICABLE
        if any(
            bool(atom.get("required")) and atom.get("outcome") == RULE_OUTCOME_MISSING
            for atom in applicable
        ):
            return RULE_OUTCOME_MISSING
        if self.threshold == COMPOSITE_THRESHOLD_ALL_REQUIRED_AND_APPLICABLE and any(
            atom.get("outcome") == RULE_OUTCOME_MISSING for atom in applicable
        ):
            return RULE_OUTCOME_PARTIAL
        return RULE_OUTCOME_SATISFIED


class SiteHealthRule:
    """One immutable, config-owned Site Health rule definition."""

    __slots__ = (
        "applicability_key",
        "category",
        "checkpoint_family",
        "composite_contract",
        "content_addressable",
        "description",
        "dimension",
        "display_label",
        "display_label_variants",
        "finding_class",
        "kind_evidence",
        "readiness_dimension",
        "readiness_weight",
        "remediation",
        "rule_id",
        "rule_version",
        "scope",
        "score_roles",
        "severity",
        "triggered_by",
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
        checkpoint_family: str = "",
        composite_contract: CompositeContract | None = None,
        content_addressable: bool = False,
        readiness_dimension: str = "",
        readiness_weight: float = 0.0,
        scope: str = RULE_SCOPE_PAGE,
        triggered_by: str = "",
        score_roles: tuple[str, ...] = (),
        web_fundamentals_area: str = "",
    ) -> None:
        if finding_class not in FINDING_CLASSES:
            raise ValueError(f"Unsupported finding class: {finding_class}")
        if kind_evidence not in KIND_EVIDENCE_CLASSES:
            raise ValueError(f"Unsupported kind evidence: {kind_evidence}")
        if scope not in RULE_SCOPES:
            raise ValueError(f"Unsupported rule scope: {scope}")
        if composite_contract is not None and not isinstance(
            composite_contract, CompositeContract
        ):
            raise ValueError("Composite contract must be a CompositeContract")
        self.rule_id = rule_id
        self.rule_version = rule_version
        self.dimension = dimension
        self.category = category
        self.severity = severity
        self.finding_class = finding_class
        self.kind_evidence = kind_evidence
        self.checkpoint_family = checkpoint_family
        self.composite_contract = composite_contract
        self.content_addressable = content_addressable
        self.readiness_dimension = readiness_dimension
        self.readiness_weight = readiness_weight
        self.scope = scope
        self.triggered_by = triggered_by
        self.score_roles = tuple(score_roles)
        self.web_fundamentals_area = web_fundamentals_area
        self.weight = weight
        self.applicability_key = applicability_key
        self.description = description
        self.remediation = remediation
        self.display_label = display_label or rule_id
        self.display_label_variants = dict(display_label_variants or {})


def validate_triggered_rule_links(
    rules: tuple[SiteHealthRule, ...],
    by_id: dict[str, SiteHealthRule],
    expectation_profiles: tuple[tuple[str, ...], ...],
) -> None:
    """Reject triggered checks without a same-role, same-dimension sibling."""
    for rule in rules:
        if rule.kind_evidence != KIND_EVIDENCE_TRIGGERED:
            continue
        sibling = by_id.get(rule.triggered_by)
        if sibling is None:
            raise ValueError(
                f"Triggered rule {rule.rule_id} requires an absence sibling"
            )
        if (
            not rule.score_roles
            or sibling.kind_evidence == KIND_EVIDENCE_TRIGGERED
            or not set(rule.score_roles).issubset(sibling.score_roles)
            or rule.readiness_dimension != sibling.readiness_dimension
            or any(
                rule.rule_id in profile and sibling.rule_id not in profile
                for profile in expectation_profiles
            )
        ):
            raise ValueError(
                f"Triggered rule {rule.rule_id} must share role and dimension "
                f"with {sibling.rule_id}"
            )
