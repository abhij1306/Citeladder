"""Organization identity and internal trust-path readiness checks."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from app.core.config.site_health_contracts import (
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_SATISFIED,
)
from app.core.config.site_health_taxonomy import ORGANIZATION_BEARING_SCHEMA_TYPES

_TRUST_PATH_TOKENS = frozenset({"about", "contact", "privacy", "policy", "terms"})


def _pass_fail(condition: bool) -> str:
    return RULE_OUTCOME_SATISFIED if condition else RULE_OUTCOME_MISSING


def check_organization_identity(facts: dict) -> tuple[str, dict]:
    blocks = (facts.get("structured_data") or {}).get("blocks") or ()
    organization_blocks = [
        block
        for block in blocks
        if str(block.get("type") or "") in ORGANIZATION_BEARING_SCHEMA_TYPES
    ]
    identities = list(filter(None, map(_organization_identity, organization_blocks)))
    return _pass_fail(bool(identities)), {
        "has_organization": bool(organization_blocks),
        "complete_identity_count": len(identities),
        "identities": identities[:4],
    }


def _organization_identity(block: dict) -> dict | None:
    name = str(block.get("name") or "")
    url = str(block.get("url") or "")
    if not name.strip() or not url.strip():
        return None
    return {"name": name[:256], "url": url[:512]}


def _terms(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def check_trust_path_present(facts: dict) -> tuple[str, dict]:
    paths: list[dict] = []
    for anchor in (facts.get("links") or {}).get("anchors") or ():
        if not anchor.get("is_internal"):
            continue
        url = str(anchor.get("url") or "")
        label = str(anchor.get("anchor_text") or "")
        try:
            path_terms = _terms(urlsplit(url).path)
        except ValueError:
            path_terms = set()
        if (path_terms | _terms(label)) & _TRUST_PATH_TOKENS:
            paths.append({"url": url[:512], "label": label[:128]})
    return _pass_fail(bool(paths)), {"trust_paths": paths[:12], "count": len(paths)}
