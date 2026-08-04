# Serialization shim: normalized brand rows -> the plain scorer config dict.
#
# Decision B-1 stores brand identity as normalized rows (``Brand`` /
# ``BrandAlias`` / ``Competitor`` / ``OwnedDomain`` / ``UnintendedDomain``),
# but the deterministic scorer (B5/B6, ``ai_visibility/scoring.py``)
# consumes a **plain dict** via
# ``ScoringConfig.from_project(config)``. Rather than rewrite the scorer to
# understand ORM rows, this shim rebuilds exactly the dict shape the scorer
# expects, so downstream scoring works unchanged.
#
# The dict shape (from the reference ``_scoring_configuration``):
#     {
#       "brand_name": str,
#       "brand_aliases": [str, ...],          # NOT including brand_name itself
#       "owned_domains": [str, ...],
#       "unintended_domains": [str, ...],
#       "competitors": [{"name","aliases","domains"}, ...],
#       "country_code": str,
#       "language_code": str,
#       "benchmark_mode": str,
#     }
# ``ScoringConfig.from_project`` prepends ``brand_name`` onto ``brand_aliases``
# itself, so this shim must NOT duplicate it into the alias list.
from __future__ import annotations

from typing import Any

from app.models.project import Project


def project_scoring_identity(project: Project) -> dict[str, Any]:
    """Rebuild the plain brand-identity dict the scorer expects from rows.

    Requires the project's ``brand`` (+ its ``aliases``), ``competitors``,
    ``owned_domains``, and ``unintended_domains`` relationships to be loaded.
    """
    brand_name, brand_aliases = _brand_identity(project)
    return {
        "brand_name": brand_name,
        "brand_aliases": [a for a in brand_aliases if a],
        "owned_domains": _domains(project.owned_domains),
        "unintended_domains": _domains(project.unintended_domains),
        "competitors": _competitors(project.competitors),
        "country_code": project.country_code or "",
        "language_code": project.language_code or "",
        "benchmark_mode": project.benchmark_mode or "",
        "products_services": _products_services(project),
    }


def _brand_identity(project: Project) -> tuple[str, list[str]]:
    if project.brand is None:
        return project.brand_name or "", []
    return project.brand.name, [alias.alias for alias in project.brand.aliases]


def _domains(rows) -> list[str]:
    return [row.domain for row in rows if row.domain]


def _competitors(rows) -> list[dict]:
    return [
        {
            "name": row.name,
            "aliases": list(row.aliases or []),
            "domains": list(row.domains or []),
        }
        for row in rows
    ]


def _products_services(project: Project) -> list[str]:
    profile = project.brand.profile if project.brand is not None else None
    return list(profile.products_services or []) if profile is not None else []
