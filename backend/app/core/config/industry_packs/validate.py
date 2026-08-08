"""Offline integrity and safety validation for the canonical industry catalog."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .catalog import (
    CATALOG_ROOT,
    CatalogError,
    canonical_content_hash,
    load_pack,
    pack_manifest,
)
from .reference import classify_page, compile_pack

EXPECTED_PACK_IDS = frozenset(
    {
        "automotive",
        "commerce",
        "education",
        "financial_services",
        "general_business",
        "healthcare",
        "hospitality",
        "local_services",
        "manufacturing",
        "media_publishing",
        "nonprofit",
        "professional_services",
        "real_estate",
        "recruiting_staffing",
        "restaurants",
        "saas",
    }
)
VALIDATED_CANDIDATE_PACK_IDS = frozenset({"commerce", "education"})
FOUNDATION_PACK_IDS = EXPECTED_PACK_IDS - VALIDATED_CANDIDATE_PACK_IDS

REQUIRED_CANONICAL_FILES = (
    "README.md",
    "PAGE_ANALYSIS_AUDIT.md",
    "PERFORMANCE_CONTRACT.md",
    "EXTENSION_CONTRACT.md",
    "EVALUATION_CONTRACT.md",
    "__init__.py",
    "benchmark.py",
    "capabilities.json",
    "catalog-summary.json",
    "catalog.py",
    "core.json",
    "reference.py",
    "registry.json",
    "schema-terms.json",
    "schema/industry-pack.schema.json",
    "sources.json",
    "taxonomy.json",
    "validate.py",
)

_SAFE_FAQ_EXPECTATIONS = {
    "unknown": "request_or_omit",
    "historical": "do_not_present_as_current",
    "conflicting": "block_authoritative_generation",
    "unsupported": "reject_or_request",
}


class CatalogValidationError(ValueError):
    """The canonical catalog failed one or more acceptance checks."""


@dataclass(frozen=True, slots=True)
class ValidationReport:
    catalog_version: str
    pack_count: int
    validated_candidate_pack_count: int
    foundation_pack_count: int
    role_fixture_case_count: int
    faq_fixture_case_count: int
    special_fixture_count: int
    counts: Mapping[str, int]
    hygiene_checked: bool


def _read_json(path: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing JSON file: {path}")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid JSON file {path}: {exc}")
    return None


def _error(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _validate_schema_subset(
    value: Any,
    schema: Mapping[str, Any],
    path: str,
    errors: list[str],
) -> None:
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _schema_type_matches(
        value,
        expected_type,
    ):
        errors.append(f"{path}: expected {expected_type}, got {type(value).__name__}")
        return

    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        errors.append(f"{path}: value {value!r} is not in enum {enum!r}")

    if isinstance(value, str):
        _validate_schema_string(value, schema, path, errors)
    if isinstance(value, list):
        _validate_schema_array(value, schema, path, errors)
    if isinstance(value, dict):
        _validate_schema_object(value, schema, path, errors)


def _validate_schema_string(
    value: str,
    schema: Mapping[str, Any],
    path: str,
    errors: list[str],
) -> None:
    minimum_length = schema.get("minLength")
    if isinstance(minimum_length, int) and len(value) < minimum_length:
        errors.append(f"{path}: string is shorter than {minimum_length}")
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
        errors.append(f"{path}: value {value!r} does not match {pattern!r}")


def _validate_schema_array(
    value: list[Any],
    schema: Mapping[str, Any],
    path: str,
    errors: list[str],
) -> None:
    minimum_items = schema.get("minItems")
    if isinstance(minimum_items, int) and len(value) < minimum_items:
        errors.append(f"{path}: array has fewer than {minimum_items} items")
    if schema.get("uniqueItems") is True:
        serialized = [
            json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value
        ]
        if len(serialized) != len(set(serialized)):
            errors.append(f"{path}: array items are not unique")
    item_schema = schema.get("items")
    if isinstance(item_schema, dict):
        for index, item in enumerate(value):
            _validate_schema_subset(item, item_schema, f"{path}[{index}]", errors)


def _validate_schema_object(
    value: Mapping[str, Any],
    schema: Mapping[str, Any],
    path: str,
    errors: list[str],
) -> None:
    required = schema.get("required", ())
    if isinstance(required, list):
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return
    for key, child_schema in properties.items():
        if key in value and isinstance(child_schema, dict):
            _validate_schema_subset(value[key], child_schema, f"{path}.{key}", errors)
    if schema.get("additionalProperties") is False:
        extras = sorted(set(value) - set(properties))
        if extras:
            errors.append(f"{path}: unexpected properties {extras!r}")


def _require_namespaced_ids(
    items: Sequence[Mapping[str, Any]],
    id_key: str,
    pack_id: str,
    label: str,
    errors: list[str],
) -> set[str]:
    values: list[str] = []
    prefix = f"{pack_id}."
    for index, item in enumerate(items):
        raw = item.get(id_key)
        if not isinstance(raw, str) or not raw:
            errors.append(f"{pack_id}.{label}[{index}] has no non-empty {id_key}")
            continue
        if not raw.startswith(prefix):
            errors.append(f"{raw}: {id_key} must be namespaced by {pack_id}")
        values.append(raw)
    if len(values) != len(set(values)):
        errors.append(f"{pack_id}: duplicate {id_key} values in {label}")
    return set(values)


def _require_refs(
    refs: Iterable[Any],
    allowed: set[str],
    context: str,
    errors: list[str],
) -> None:
    for ref in refs:
        if not isinstance(ref, str) or ref not in allowed:
            errors.append(f"{context}: unknown reference {ref!r}")


def _validate_signal(
    signal: Mapping[str, Any],
    *,
    pack_id: str,
    role_id: str,
    expected_polarity: str,
    fields: set[str],
    operators: set[str],
    seen_ids: set[str],
    errors: list[str],
) -> None:
    signal_id = signal.get("signal_id")
    if not isinstance(signal_id, str) or not signal_id.startswith(f"{pack_id}."):
        errors.append(f"{role_id}: invalid namespaced signal_id {signal_id!r}")
    elif signal_id in seen_ids:
        errors.append(f"{pack_id}: duplicate signal_id {signal_id}")
    else:
        seen_ids.add(signal_id)
    if signal.get("field") not in fields:
        errors.append(f"{signal_id}: unknown signal field {signal.get('field')!r}")
    if signal.get("operator") not in operators:
        errors.append(
            f"{signal_id}: unknown signal operator {signal.get('operator')!r}"
        )
    if signal.get("polarity") != expected_polarity:
        errors.append(
            f"{signal_id}: expected polarity {expected_polarity!r}, "
            f"got {signal.get('polarity')!r}"
        )
    _validate_signal_weight(signal, signal_id, expected_polarity, errors)
    _validate_signal_matcher(signal, signal_id, errors)


def _validate_signal_weight(
    signal: Mapping[str, Any],
    signal_id: Any,
    expected_polarity: str,
    errors: list[str],
) -> None:
    """Weight is numeric and its sign agrees with the declared polarity."""

    weight = signal.get("weight")
    if not isinstance(weight, (int, float)) or isinstance(weight, bool):
        errors.append(f"{signal_id}: weight must be numeric")
    elif expected_polarity == "positive" and weight <= 0:
        errors.append(f"{signal_id}: positive weight must be greater than zero")
    elif expected_polarity == "negative" and weight >= 0:
        errors.append(f"{signal_id}: negative weight must be less than zero")


def _validate_signal_matcher(
    signal: Mapping[str, Any],
    signal_id: Any,
    errors: list[str],
) -> None:
    """A regex signal needs a compilable pattern; every other kind needs values."""

    if signal.get("operator") != "regex":
        values = signal.get("values")
        if not isinstance(values, list) or not values:
            errors.append(f"{signal_id}: non-regex signal requires values")
        return
    pattern = signal.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        errors.append(f"{signal_id}: regex signal requires a pattern")
        return
    try:
        re.compile(pattern)
    except re.error as exc:
        errors.append(f"{signal_id}: invalid regex: {exc}")


@dataclass(frozen=True)
class _PackIds:
    """Namespaced IDs declared by one pack, used to resolve internal references."""

    roles: set[str]
    entities: set[str]
    predicates: set[str]
    questions: set[str]
    stages: set[str]
    outcomes: set[str]


def _collect_pack_ids(
    pack_id: str,
    sections: Mapping[str, Sequence[Mapping[str, Any]]],
    errors: list[str],
) -> _PackIds:
    """Every declared ID is namespaced by its pack and unique within its section."""

    def ids(label: str, id_key: str) -> set[str]:
        return _require_namespaced_ids(sections[label], id_key, pack_id, label, errors)

    for label, id_key in (
        ("relation_types", "relation_type_id"),
        ("analysis_rules", "rule_id"),
        ("brief_templates", "brief_id"),
        ("prompt_archetypes", "prompt_id"),
    ):
        ids(label, id_key)

    journeys = sections["journeys"]
    stage_items = [stage for journey in journeys for stage in journey.get("stages", ())]
    outcome_items = [
        outcome for journey in journeys for outcome in journey.get("outcomes", ())
    ]
    return _PackIds(
        roles=ids("page_roles", "role_id"),
        entities=ids("entity_types", "entity_type_id"),
        predicates=ids("assertion_predicates", "predicate_id"),
        questions=ids("question_contracts", "question_id"),
        stages=_require_namespaced_ids(
            stage_items, "stage_id", pack_id, "journey_stages", errors
        ),
        outcomes=_require_namespaced_ids(
            outcome_items, "outcome_id", pack_id, "outcomes", errors
        ),
    )


def _validate_classification_policy(
    pack: Mapping[str, Any],
    pack_id: str,
    core: Mapping[str, Any],
    errors: list[str],
) -> None:
    """Classifier thresholds are numeric and the two safety switches stay set."""

    policy = pack.get("classification_policy", {})
    if not isinstance(policy, dict):
        errors.append(f"{pack_id}.classification_policy must be an object")
        policy = {}
    if policy.get("classifier_version") != core.get("classifier_version"):
        errors.append(f"{pack_id}: classifier version does not match core")
    for key in (
        "minimum_score",
        "minimum_margin",
        "high_confidence_score",
        "maximum_secondary_roles",
        "maximum_evidence_records",
        "maximum_alternatives",
        "maximum_conflicts",
    ):
        if not isinstance(policy.get(key), (int, float)):
            errors.append(f"{pack_id}.classification_policy.{key} must be numeric")
    if policy.get("schema_only_may_classify") is not False:
        errors.append(f"{pack_id}: schema-only classification must remain disabled")
    if policy.get("abstain_on_tie") is not True:
        errors.append(f"{pack_id}: tie abstention must remain enabled")


def _validate_role_signals(
    role: Mapping[str, Any],
    *,
    pack_id: str,
    role_id: str,
    fields: set[str],
    operators: set[str],
    signal_ids: set[str],
    errors: list[str],
) -> None:
    """Positive and negative classifier signals for one role."""

    for key, polarity in (("signals", "positive"), ("negative_signals", "negative")):
        for signal in role.get(key, ()):
            _validate_signal(
                signal,
                pack_id=pack_id,
                role_id=role_id,
                expected_polarity=polarity,
                fields=fields,
                operators=operators,
                seen_ids=signal_ids,
                errors=errors,
            )


def _validate_pack_roles(
    roles: Sequence[Mapping[str, Any]],
    *,
    pack_id: str,
    core: Mapping[str, Any],
    ids: _PackIds,
    schema_types: set[str],
    errors: list[str],
) -> None:
    """Each role resolves its page kinds, questions, entities, schema, and signals."""

    fields = set(core.get("classifier_signal_fields", ()))
    operators = set(core.get("classifier_operators", ()))
    page_kinds = set(core.get("generic_page_kinds", ()))
    signal_ids: set[str] = set()

    for role in roles:
        role_id = str(role.get("role_id"))
        for key, allowed in (
            ("page_kinds", page_kinds),
            ("required_question_ids", ids.questions),
            ("entity_type_ids", ids.entities),
        ):
            _require_refs(role.get(key, ()), allowed, f"{role_id}.{key}", errors)
        schema_expectations = role.get("schema_expectations", {})
        _require_refs(
            schema_expectations.get("recommended_types", ()),
            schema_types,
            f"{role_id}.schema_expectations.recommended_types",
            errors,
        )
        if schema_expectations.get("rich_result_guaranteed") is not False:
            errors.append(f"{role_id}: rich-result guarantees are forbidden")
        _validate_role_signals(
            role,
            pack_id=pack_id,
            role_id=role_id,
            fields=fields,
            operators=operators,
            signal_ids=signal_ids,
            errors=errors,
        )


def _validate_pack_graph(
    sections: Mapping[str, Sequence[Mapping[str, Any]]],
    ids: _PackIds,
    errors: list[str],
) -> None:
    """Entity attributes, predicate subjects, and relation endpoints resolve."""

    for entity in sections["entity_types"]:
        attribute_names = {
            str(item.get("name"))
            for item in entity.get("attributes", ())
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        _require_refs(
            entity.get("identity_fields", ()),
            attribute_names,
            f"{entity.get('entity_type_id')}.identity_fields",
            errors,
        )

    for predicate in sections["assertion_predicates"]:
        _require_refs(
            predicate.get("subject_entity_type_ids", ()),
            ids.entities,
            f"{predicate.get('predicate_id')}.subject_entity_type_ids",
            errors,
        )

    for relation in sections["relation_types"]:
        relation_id = str(relation.get("relation_type_id"))
        for key in ("source_entity_type_ids", "target_entity_type_ids"):
            _require_refs(
                relation.get(key, ()), ids.entities, f"{relation_id}.{key}", errors
            )


def _validate_pack_journeys(
    journeys: Sequence[Mapping[str, Any]],
    ids: _PackIds,
    errors: list[str],
) -> None:
    """Journey audiences and every stage's roles, questions, and outcomes resolve."""

    for journey in journeys:
        journey_id = str(journey.get("journey_id"))
        _require_refs(
            journey.get("audience_entity_type_ids", ()),
            ids.entities,
            f"{journey_id}.audience_entity_type_ids",
            errors,
        )
        for stage in journey.get("stages", ()):
            stage_id = str(stage.get("stage_id"))
            for key, allowed in (
                ("required_role_ids", ids.roles),
                ("required_question_ids", ids.questions),
                ("outcome_ids", ids.outcomes),
            ):
                _require_refs(stage.get(key, ()), allowed, f"{stage_id}.{key}", errors)


def _validate_pack_outputs(
    sections: Mapping[str, Sequence[Mapping[str, Any]]],
    ids: _PackIds,
    errors: list[str],
) -> None:
    """Question contracts, brief templates, and prompt archetypes resolve."""

    for question in sections["question_contracts"]:
        question_id = str(question.get("question_id"))
        for key, allowed in (
            ("applicable_role_ids", ids.roles),
            ("required_predicate_ids", ids.predicates),
            ("required_entity_type_ids", ids.entities),
        ):
            _require_refs(
                question.get(key, ()), allowed, f"{question_id}.{key}", errors
            )
        _require_refs(
            (question.get("journey_stage_id"),),
            ids.stages,
            f"{question_id}.journey_stage_id",
            errors,
        )

    for brief in sections["brief_templates"]:
        brief_id = str(brief.get("brief_id"))
        _require_refs(
            brief.get("role_ids", ()), ids.roles, f"{brief_id}.role_ids", errors
        )
        if brief.get("human_review_required") is not True:
            errors.append(f"{brief_id}: human review must remain required")

    for prompt in sections["prompt_archetypes"]:
        _require_refs(
            prompt.get("journey_stage_ids", ()),
            ids.stages,
            f"{prompt.get('prompt_id')}.journey_stage_ids",
            errors,
        )


def _validate_pack_policies(
    pack: Mapping[str, Any], pack_id: str, errors: list[str]
) -> None:
    """Generation and review guarantees a pack may never relax."""

    generation = pack.get("generation_policy", {})
    expected_generation = {
        "unknown_fact_behavior": "request_or_omit",
        "conflict_behavior": "block_authoritative_generation",
        "historical_fact_behavior": "never_present_as_current",
        "numeric_claims_require_direct_evidence": True,
        "faqpage_requires_visible_content_parity": True,
        "faq_rich_result_guaranteed": False,
    }
    for key, expected in expected_generation.items():
        if generation.get(key) != expected:
            errors.append(
                f"{pack_id}.generation_policy.{key}: expected {expected!r}, "
                f"got {generation.get(key)!r}"
            )
    review = pack.get("review_requirements", {})
    if review.get("project_facts_may_mutate_pack") is not False:
        errors.append(f"{pack_id}: project facts must not mutate shared packs")
    if review.get("authoritative_findings_enabled") is not False:
        errors.append(f"{pack_id}: authoritative findings must remain disabled")


def _validate_pack(
    pack: Mapping[str, Any],
    *,
    core: Mapping[str, Any],
    schema_types: set[str],
    capability_ids: set[str],
    errors: list[str],
) -> dict[str, int]:
    """Validate one pack's internal references and policies. Returns its counts."""

    pack_id = str(pack.get("pack_id", ""))
    sections: dict[str, Sequence[Mapping[str, Any]]] = {
        label: tuple(pack.get(label, ()))
        for label in (
            "page_roles",
            "entity_types",
            "assertion_predicates",
            "relation_types",
            "journeys",
            "question_contracts",
            "analysis_rules",
            "brief_templates",
            "prompt_archetypes",
        )
    }
    ids = _collect_pack_ids(pack_id, sections, errors)

    _require_refs(
        pack.get("capability_ids", ()),
        capability_ids,
        f"{pack_id}.capability_ids",
        errors,
    )
    _validate_classification_policy(pack, pack_id, core, errors)
    _validate_pack_roles(
        sections["page_roles"],
        pack_id=pack_id,
        core=core,
        ids=ids,
        schema_types=schema_types,
        errors=errors,
    )
    _validate_pack_graph(sections, ids, errors)
    _validate_pack_journeys(sections["journeys"], ids, errors)
    _validate_pack_outputs(sections, ids, errors)
    _validate_pack_policies(pack, pack_id, errors)

    # Counts are of declared items, not of unique IDs: a duplicate is an error
    # reported above, and the summary must still describe what the file holds.
    journeys = sections["journeys"]
    counts = {label: len(items) for label, items in sections.items()}
    counts["journey_stages"] = sum(
        len(tuple(journey.get("stages", ()))) for journey in journeys
    )
    counts["outcomes"] = sum(
        len(tuple(journey.get("outcomes", ()))) for journey in journeys
    )
    return counts


def _validate_role_case(
    case: Mapping[str, Any],
    case_id: str,
    compiled: Any,
    errors: list[str],
) -> None:
    """Classify one fixture case and compare it with the labelled expectation."""

    result = classify_page(compiled, case.get("facts", {}))
    if "expected_role_id" in case and result["primary_role_id"] != case.get(
        "expected_role_id"
    ):
        # The abstention reason is the first thing you want when a classifier
        # regresses, so it stays on this message specifically.
        errors.append(
            f"{case_id}: expected role {case.get('expected_role_id')!r}, "
            f"got {result['primary_role_id']!r} ({result['abstention_reason']!r})"
        )
    for key, result_key, label in (
        ("expected_abstention_reason", "abstention_reason", "abstention"),
        ("expected_temporal_state", "temporal_state", "temporal state"),
    ):
        if key in case and result[result_key] != case.get(key):
            errors.append(
                f"{case_id}: expected {label} {case.get(key)!r}, "
                f"got {result[result_key]!r}"
            )
    if case.get("expected_conflict_disclosure") and not result["conflicts"]:
        errors.append(f"{case_id}: expected conflict disclosure")
    for result_key, bound, label in (
        ("evidence", compiled.maximum_evidence_records, "evidence"),
        ("alternatives", compiled.maximum_alternatives, "alternatives"),
        ("conflicts", compiled.maximum_conflicts, "conflicts"),
    ):
        if len(result[result_key]) > bound:
            errors.append(f"{case_id}: {label} output exceeds configured bound")


def _validate_role_fixture(
    pack: Mapping[str, Any],
    compiled: Any,
    fixture: Mapping[str, Any],
    errors: list[str],
) -> int:
    pack_id = str(pack["pack_id"])
    if fixture.get("pack_id") != pack_id:
        errors.append(f"{pack_id}: role fixture pack_id mismatch")
    cases = fixture.get("cases", ())
    if not isinstance(cases, list):
        errors.append(f"{pack_id}: role fixture cases must be an array")
        return 0
    case_ids: set[str] = set()
    case_classes: set[str] = set()
    for index, case in enumerate(cases):
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{pack_id}: role fixture case {index} has no case_id")
            continue
        if case_id in case_ids:
            errors.append(f"{pack_id}: duplicate role fixture case_id {case_id}")
        case_ids.add(case_id)
        case_classes.add(str(case.get("case_class")))
        _validate_role_case(case, case_id, compiled, errors)
    required_classes = set(pack.get("evaluation", {}).get("required_case_classes", ()))
    missing_classes = sorted(required_classes - case_classes)
    if missing_classes:
        errors.append(
            f"{pack_id}: role fixture misses required classes {missing_classes!r}"
        )
    return len(cases)


def _validate_faq_case(
    case: Mapping[str, Any],
    case_id: str,
    case_class: str,
    question_ids: set[Any],
    errors: list[str],
) -> None:
    """One FAQ fixture case: known question, safe expectation, parity honesty."""

    if case.get("question_id") not in question_ids:
        errors.append(f"{case_id}: unknown question_id {case.get('question_id')!r}")
    expected_safe = _SAFE_FAQ_EXPECTATIONS.get(case_class)
    if expected_safe and case.get("expected") != expected_safe:
        errors.append(
            f"{case_id}: unsafe expectation {case.get('expected')!r}; "
            f"expected {expected_safe!r}"
        )
    if case_class != "schema_parity":
        return
    visible = case.get("visible_answer")
    expected = "pass" if visible and visible == case.get("schema_answer") else "reject"
    if case.get("expected") != expected:
        errors.append(f"{case_id}: invalid visible/schema parity expectation")


def _validate_faq_fixture(
    pack: Mapping[str, Any],
    fixture: Mapping[str, Any],
    errors: list[str],
) -> int:
    pack_id = str(pack["pack_id"])
    question_ids = {item["question_id"] for item in pack["question_contracts"]}
    if fixture.get("pack_id") != pack_id:
        errors.append(f"{pack_id}: FAQ fixture pack_id mismatch")
    cases = fixture.get("cases", ())
    if not isinstance(cases, list):
        errors.append(f"{pack_id}: FAQ fixture cases must be an array")
        return 0
    seen_ids: set[str] = set()
    seen_classes: set[str] = set()
    for index, case in enumerate(cases):
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{pack_id}: FAQ fixture case {index} has no case_id")
            continue
        if case_id in seen_ids:
            errors.append(f"{pack_id}: duplicate FAQ fixture case_id {case_id}")
        seen_ids.add(case_id)
        case_class = str(case.get("case_class"))
        seen_classes.add(case_class)
        _validate_faq_case(case, case_id, case_class, question_ids, errors)
    required = {
        "supported",
        "unknown",
        "historical",
        "conflicting",
        "unsupported",
        "schema_parity",
    }
    missing = sorted(required - seen_classes)
    if missing:
        errors.append(f"{pack_id}: FAQ fixture misses classes {missing!r}")
    return len(cases)


def _validate_special_fixtures(
    packs: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> int:
    count = 0
    commerce_path = CATALOG_ROOT / "fixtures/commerce/catalog-scenarios.json"
    commerce = _read_json(commerce_path, errors)
    if isinstance(commerce, dict):
        scenarios = commerce.get("scenarios", ())
        commerce_roles = {item["role_id"] for item in packs["commerce"]["page_roles"]}
        scenario_ids = set()
        for scenario in scenarios:
            scenario_id = scenario.get("scenario_id")
            if not isinstance(scenario_id, str) or not scenario_id:
                errors.append("commerce catalog scenario has no scenario_id")
                continue
            if scenario_id in scenario_ids:
                errors.append(f"duplicate commerce scenario_id {scenario_id}")
            scenario_ids.add(scenario_id)
            _require_refs(
                scenario.get("roles", ()),
                commerce_roles,
                f"commerce scenario {scenario_id}",
                errors,
            )
            if not scenario.get("expected"):
                errors.append(f"commerce scenario {scenario_id} has no expectations")
        required_scenarios = {
            "category_with_filters",
            "discontinued_product",
            "pdp_current_offer",
            "policy_scope",
            "variant_family",
            "visible_schema_price_conflict",
        }
        missing = sorted(required_scenarios - scenario_ids)
        if missing:
            errors.append(f"commerce scenarios missing {missing!r}")
        count += len(scenarios)

    education_path = CATALOG_ROOT / "fixtures/education/asian-school-public-labels.json"
    education = _read_json(education_path, errors)
    if isinstance(education, dict):
        if education.get("pack_id") != "education":
            errors.append("education public-label fixture pack_id mismatch")
        boundary = education.get("source_boundary", {})
        if boundary.get("customer_facts_are_not_shared_pack_knowledge") is not True:
            errors.append("education public-label fixture lacks customer-fact boundary")
        education_roles = {item["role_id"] for item in packs["education"]["page_roles"]}
        _require_refs(
            education.get("required_role_families", ()),
            education_roles,
            "education public-label required_role_families",
            errors,
        )
        if not education.get("required_semantic_labels"):
            errors.append("education public-label fixture has no semantic labels")
        count += 1
    return count


def _computed_counts(
    packs: Mapping[str, Mapping[str, Any]],
    taxonomy_data: Mapping[str, Any],
    capabilities_data: Mapping[str, Any],
    schema_terms: Mapping[str, Any],
    per_pack_counts: Mapping[str, Mapping[str, int]],
) -> dict[str, int]:
    keys = (
        "page_roles",
        "entity_types",
        "assertion_predicates",
        "relation_types",
        "journeys",
        "journey_stages",
        "outcomes",
        "question_contracts",
        "analysis_rules",
        "brief_templates",
        "prompt_archetypes",
    )
    result = {key: sum(item[key] for item in per_pack_counts.values()) for key in keys}
    result.update(
        {
            "packs": len(packs),
            "validated_candidate_packs": sum(
                pack["maturity"] == "validated_candidate" for pack in packs.values()
            ),
            "foundation_packs": sum(
                pack["maturity"] == "foundation" for pack in packs.values()
            ),
            "taxonomy_nodes": len(taxonomy_data.get("nodes", ())),
            "capabilities": len(capabilities_data.get("capabilities", ())),
            "schema_types": len(schema_terms.get("types", ())),
            "schema_properties": len(schema_terms.get("properties", ())),
        }
    )
    return result


def _validate_hygiene(errors: list[str]) -> None:
    backend_root = CATALOG_ROOT.parents[3]
    repo_root = CATALOG_ROOT.parents[4]
    forbidden_exact = (
        repo_root / ".industry_kb_transfer",
        repo_root / ".registry_bundle.b64",
        repo_root / ".runtime/build_industry_catalog.py",
        backend_root / "app/core/config/industry_registry",
        backend_root / "app/core/config/industry_registry.json",
        backend_root / "app/core/config/industry_registry.schema.json",
        backend_root / "calibrate_industry_fixtures.py",
        backend_root / "inspect_industry_conflicts.py",
        backend_root / "replay_industry_catalog.py",
    )
    for path in forbidden_exact:
        if path.exists():
            errors.append(f"forbidden duplicate or transient asset exists: {path}")

    runtime = repo_root / ".runtime"
    if runtime.exists():
        for pattern in ("industry_catalog*", "industry-catalog*"):
            for path in runtime.glob(pattern):
                errors.append(f"forbidden transient asset exists: {path}")
    for path in backend_root.glob("tmp_*"):
        errors.append(f"forbidden backend temporary asset exists: {path}")

    old_pack_docs = repo_root / "docs/plans/industry-packs"
    if old_pack_docs.exists():
        extras = sorted(
            path
            for path in old_pack_docs.rglob("*")
            if path.is_file() and path.name != "README.md"
        )
        for path in extras:
            errors.append(f"duplicate industry-pack definition remains: {path}")


def _validate_required_files(errors: list[str]) -> None:
    """Every canonical file exists and every JSON file in the tree parses."""

    for relative in REQUIRED_CANONICAL_FILES:
        _error(
            errors,
            (CATALOG_ROOT / relative).is_file(),
            f"missing canonical file: {relative}",
        )
    for path in sorted(CATALOG_ROOT.rglob("*.json")):
        _read_json(path, errors)


def _load_canonical_docs(errors: list[str]) -> tuple[Any, ...]:
    """Load the seven catalog documents, or abort — nothing else can be checked."""

    docs = tuple(
        _read_json(CATALOG_ROOT / relative, errors)
        for relative in (
            "registry.json",
            "core.json",
            "capabilities.json",
            "taxonomy.json",
            "schema-terms.json",
            "catalog-summary.json",
            "schema/industry-pack.schema.json",
        )
    )
    if not all(isinstance(doc, dict) for doc in docs):
        raise CatalogValidationError("\n".join(errors))
    return docs


def _validate_registry_identity(
    registry_data: Mapping[str, Any],
    pack_paths: Sequence[Path],
    errors: list[str],
) -> None:
    """Registry IDs, pack filenames, and the fallback pack match the catalog."""

    registry_ids = {entry.get("pack_id") for entry in registry_data.get("packs", ())}
    if registry_ids != EXPECTED_PACK_IDS:
        errors.append(
            "registry pack IDs differ from required catalog: "
            f"expected {sorted(EXPECTED_PACK_IDS)!r}, got {sorted(registry_ids)!r}"
        )
    file_ids = {path.stem for path in pack_paths}
    if file_ids != EXPECTED_PACK_IDS:
        errors.append(
            "pack filenames differ from required catalog: "
            f"expected {sorted(EXPECTED_PACK_IDS)!r}, got {sorted(file_ids)!r}"
        )
    if registry_data.get("general_fallback_pack_id") != "general_business":
        errors.append("registry general fallback must be general_business")


def _collect_term_ids(
    capabilities_data: Mapping[str, Any],
    schema_terms: Mapping[str, Any],
    errors: list[str],
) -> tuple[Sequence[Any], set[str], set[str]]:
    """Capability and Schema.org term identity, checked for duplicates."""

    capability_items = capabilities_data.get("capabilities", ())
    capability_ids = {
        str(item.get("capability_id"))
        for item in capability_items
        if isinstance(item, dict) and item.get("capability_id")
    }
    if len(capability_ids) != len(capability_items):
        errors.append("capability IDs must be unique and non-empty")

    type_items = schema_terms.get("types", ())
    property_items = schema_terms.get("properties", ())
    schema_types = {
        str(item.get("name"))
        for item in type_items
        if isinstance(item, dict) and item.get("name")
    }
    schema_properties = {
        str(item.get("name"))
        for item in property_items
        if isinstance(item, dict) and item.get("name")
    }
    if len(schema_types) != len(type_items):
        errors.append("Schema.org type snapshot contains duplicates or invalid names")
    if len(schema_properties) != len(property_items):
        errors.append(
            "Schema.org property snapshot contains duplicates or invalid names"
        )
    return capability_items, capability_ids, schema_types


def _validate_entry_identity(
    pack: Mapping[str, Any],
    entry: Mapping[str, Any],
    manifest: Mapping[str, Any],
    pack_id: str,
    errors: list[str],
) -> None:
    """Content hashes and maturity agree between registry, manifest, and pack."""

    if canonical_content_hash(pack) != entry.get("content_hash"):
        errors.append(f"{pack_id}: direct registry content hash mismatch")
    if manifest["pack_content_hash"] != entry.get("content_hash"):
        errors.append(f"{pack_id}: manifest content hash mismatch")
    if pack.get("maturity") != entry.get("maturity"):
        errors.append(f"{pack_id}: registry maturity differs from pack")
    expected_maturity = (
        "validated_candidate"
        if pack_id in VALIDATED_CANDIDATE_PACK_IDS
        else "foundation"
    )
    if pack.get("maturity") != expected_maturity:
        errors.append(
            f"{pack_id}: expected maturity {expected_maturity}, "
            f"got {pack.get('maturity')!r}"
        )


def _validate_entry_fixtures(
    pack: Mapping[str, Any],
    compiled: Any,
    errors: list[str],
) -> tuple[int, int]:
    """Role and FAQ fixture cases for one pack. Returns the two case counts."""

    evaluation = pack.get("evaluation", {})
    role_fixture = _read_json(
        CATALOG_ROOT / str(evaluation.get("role_fixture", "")), errors
    )
    faq_fixture = _read_json(
        CATALOG_ROOT / str(evaluation.get("faq_fixture", "")), errors
    )
    role_cases = (
        _validate_role_fixture(pack, compiled, role_fixture, errors)
        if isinstance(role_fixture, dict)
        else 0
    )
    faq_cases = (
        _validate_faq_fixture(pack, faq_fixture, errors)
        if isinstance(faq_fixture, dict)
        else 0
    )
    return role_cases, faq_cases


def _validate_registry_entry(
    entry: Any,
    *,
    core: Mapping[str, Any],
    pack_schema: Mapping[str, Any],
    schema_types: set[str],
    capability_ids: set[str],
    packs: dict[str, Mapping[str, Any]],
    per_pack_counts: dict[str, dict[str, int]],
    errors: list[str],
) -> tuple[int, int]:
    """Validate one registry entry and its pack. Returns fixture case counts."""

    if not isinstance(entry, dict):
        errors.append("registry pack entry must be an object")
        return 0, 0
    pack_id = entry.get("pack_id")
    version = entry.get("version")
    if not isinstance(pack_id, str) or not isinstance(version, str):
        errors.append(f"invalid registry pack entry: {entry!r}")
        return 0, 0
    if entry.get("authoritative_findings_enabled") is not False:
        errors.append(f"{pack_id}: registry authoritative findings must be false")
    try:
        frozen_pack = load_pack(pack_id, version)
        manifest = pack_manifest(pack_id, version)
    except CatalogError as exc:
        errors.append(str(exc))
        return 0, 0

    # Reload the canonical JSON after the exact loader has verified it.
    pack = _read_json(CATALOG_ROOT / str(entry.get("file")), errors)
    if not isinstance(pack, dict):
        return 0, 0

    _validate_entry_identity(pack, entry, manifest, pack_id, errors)
    _validate_schema_subset(pack, pack_schema, pack_id, errors)
    packs[pack_id] = pack
    per_pack_counts[pack_id] = _validate_pack(
        pack,
        core=core,
        schema_types=schema_types,
        capability_ids=capability_ids,
        errors=errors,
    )
    return _validate_entry_fixtures(
        pack, compile_pack(frozen_pack, manifest=manifest), errors
    )


def _validate_capability_compatibility(
    capability_items: Sequence[Any],
    packs: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> None:
    """Declared compatibility matches the packs that actually opt in."""

    for capability in capability_items:
        capability_id = str(capability.get("capability_id"))
        compatible = set(capability.get("compatible_pack_ids", ()))
        _require_refs(
            compatible,
            set(packs),
            f"capability {capability_id}.compatible_pack_ids",
            errors,
        )
        expected = {
            pack_id
            for pack_id, pack in packs.items()
            if capability_id in pack.get("capability_ids", ())
        }
        if compatible != expected:
            errors.append(
                f"capability {capability_id}: compatibility differs from pack use; "
                f"expected {sorted(expected)!r}, got {sorted(compatible)!r}"
            )
        if capability.get("may_weaken_shared_controls") is not False:
            errors.append(f"capability {capability_id}: controls may not be weakened")


def _validate_taxonomy_node(
    node: Mapping[str, Any],
    *,
    packs: Mapping[str, Mapping[str, Any]],
    capability_ids: set[str],
    seen: set[str],
    errors: list[str],
) -> None:
    """One taxonomy node: unique ID, resolvable pack, capabilities the pack has."""

    taxonomy_id = node.get("taxonomy_id")
    if not isinstance(taxonomy_id, str) or not taxonomy_id:
        errors.append("taxonomy node has no taxonomy_id")
        return
    if taxonomy_id in seen:
        errors.append(f"duplicate taxonomy_id {taxonomy_id}")
    seen.add(taxonomy_id)

    primary_pack_id = node.get("primary_pack_id")
    recommended = set(node.get("recommended_capability_ids", ()))
    _require_refs(
        (primary_pack_id,),
        set(packs),
        f"taxonomy {taxonomy_id}.primary_pack_id",
        errors,
    )
    _require_refs(
        recommended,
        capability_ids,
        f"taxonomy {taxonomy_id}.recommended_capability_ids",
        errors,
    )
    if isinstance(primary_pack_id, str) and primary_pack_id in packs:
        extra = recommended - set(packs[primary_pack_id].get("capability_ids", ()))
        if extra:
            errors.append(
                f"taxonomy {taxonomy_id}: capabilities not in primary pack {extra!r}"
            )


def _validate_taxonomy(
    taxonomy_data: Mapping[str, Any],
    packs: Mapping[str, Mapping[str, Any]],
    capability_ids: set[str],
    errors: list[str],
) -> None:
    """Every taxonomy node resolves, and every pack has a general node."""

    seen: set[str] = set()
    for node in taxonomy_data.get("nodes", ()):
        _validate_taxonomy_node(
            node,
            packs=packs,
            capability_ids=capability_ids,
            seen=seen,
            errors=errors,
        )
    for pack_id in packs:
        if f"{pack_id}.general" not in seen:
            errors.append(f"taxonomy has no general node for {pack_id}")


def _validate_no_customer_markers(
    pack_paths: Sequence[Path], errors: list[str]
) -> None:
    """Shared catalog files carry no customer facts (invariants.md section 10)."""

    shared_paths = [
        CATALOG_ROOT / name
        for name in (
            "core.json",
            "registry.json",
            "capabilities.json",
            "taxonomy.json",
            "schema-terms.json",
        )
    ] + list(pack_paths)
    for path in shared_paths:
        text = path.read_text(encoding="utf-8").casefold()
        for marker in ("the asian school", "theasianschool.net"):
            if marker in text:
                errors.append(f"customer fact marker {marker!r} leaked into {path}")


def _validate_sources(errors: list[str]) -> None:
    """Source IDs are unique and every source URL is HTTPS."""

    sources = _read_json(CATALOG_ROOT / "sources.json", errors)
    if not isinstance(sources, dict):
        return
    source_items = sources.get("sources", ())
    source_ids = [item.get("source_id") for item in source_items]
    if len(source_ids) != len(set(source_ids)):
        errors.append("source IDs must be unique")
    for item in source_items:
        url = item.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            errors.append(f"source URL must be HTTPS: {url!r}")


def validate_catalog(*, check_hygiene: bool = True) -> ValidationReport:
    """Validate the complete catalog or raise one aggregated error.

    Each phase appends to a shared ``errors`` list rather than raising, so one
    run reports every problem instead of stopping at the first.
    """

    errors: list[str] = []
    _validate_required_files(errors)
    (
        registry_data,
        core,
        capabilities_data,
        taxonomy_data,
        schema_terms,
        summary,
        pack_schema,
    ) = _load_canonical_docs(errors)

    pack_paths = sorted((CATALOG_ROOT / "packs").glob("*.json"))
    _validate_registry_identity(registry_data, pack_paths, errors)
    capability_items, capability_ids, schema_types = _collect_term_ids(
        capabilities_data, schema_terms, errors
    )

    packs: dict[str, Mapping[str, Any]] = {}
    per_pack_counts: dict[str, dict[str, int]] = {}
    role_fixture_count = 0
    faq_fixture_count = 0
    for entry in registry_data.get("packs", ()):
        role_cases, faq_cases = _validate_registry_entry(
            entry,
            core=core,
            pack_schema=pack_schema,
            schema_types=schema_types,
            capability_ids=capability_ids,
            packs=packs,
            per_pack_counts=per_pack_counts,
            errors=errors,
        )
        role_fixture_count += role_cases
        faq_fixture_count += faq_cases

    _validate_capability_compatibility(capability_items, packs, errors)
    _validate_taxonomy(taxonomy_data, packs, capability_ids, errors)
    _validate_no_customer_markers(pack_paths, errors)

    special_fixture_count = _validate_special_fixtures(packs, errors)
    computed = _computed_counts(
        packs, taxonomy_data, capabilities_data, schema_terms, per_pack_counts
    )
    if summary.get("catalog_version") != registry_data.get("catalog_version"):
        errors.append("catalog summary version differs from registry")
    if summary.get("counts") != computed:
        errors.append(
            "catalog-summary counts differ from computed counts: "
            f"expected {computed!r}, got {summary.get('counts')!r}"
        )
    _validate_sources(errors)

    if check_hygiene:
        _validate_hygiene(errors)
    if errors:
        numbered = "\n".join(
            f"{index + 1}. {message}" for index, message in enumerate(errors)
        )
        raise CatalogValidationError(
            f"industry catalog validation failed ({len(errors)} errors):\n{numbered}"
        )

    return ValidationReport(
        catalog_version=str(registry_data["catalog_version"]),
        pack_count=len(packs),
        validated_candidate_pack_count=len(VALIDATED_CANDIDATE_PACK_IDS),
        foundation_pack_count=len(FOUNDATION_PACK_IDS),
        role_fixture_case_count=role_fixture_count,
        faq_fixture_case_count=faq_fixture_count,
        special_fixture_count=special_fixture_count,
        counts=computed,
        hygiene_checked=check_hygiene,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-hygiene",
        action="store_true",
        help="Skip repository duplicate and transient checks while developing.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        report = validate_catalog(check_hygiene=not args.skip_hygiene)
    except CatalogValidationError as exc:
        print(str(exc))
        return 1
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
