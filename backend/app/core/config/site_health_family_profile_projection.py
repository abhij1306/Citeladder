"""Read projections over the canonical Site Health capability-family profile."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict

from app.core.config.site_health_family_profile import (
    CAPABILITY_FAMILY_MANIFEST,
    CLASSIFIED_KIND_FAMILY_PROFILE,
    PROFILE_STATUS_MEASUREMENT_GAP,
    profile_rows,
)


def measurement_gap_reasons(
    page_kind: str,
    page_traits: Iterable[str] = (),
    context: Mapping[str, object] | None = None,
) -> dict[str, str]:
    return {
        row.family_id: row.reason
        for row in profile_rows(page_kind, page_traits, context)
        if row.status == PROFILE_STATUS_MEASUREMENT_GAP
    }


def serialized_family_profile() -> str:
    payload = {
        "families": [
            asdict(family)
            for family in sorted(
                CAPABILITY_FAMILY_MANIFEST, key=lambda item: item.family_id
            )
        ],
        "profile": [asdict(row) for row in CLASSIFIED_KIND_FAMILY_PROFILE],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
