"""Frozen obscure-brand identity evidence for onboarding v7 regressions.

The corpus is deliberately offline. It records bounded facts that a retrieved
source established; it is not a cache used by production onboarding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ObscureBrandCase:
    brand_name: str
    owned_domain: str
    expected_category_terms: tuple[str, ...]
    frozen_evidence: tuple[str, ...]
    forbidden_category_terms: tuple[str, ...] = ()


OBSCURE_BRAND_CASES: Final = (
    ObscureBrandCase(
        "TempPro",
        "temppro.com",
        ("meat thermometer", "cooking thermometer"),
        ("Wireless and smart meat thermometers and temperature tools.",),
    ),
    ObscureBrandCase(
        "Lanhtropy",
        "lanhtropy.com",
        ("linen", "womenswear"),
        (
            "The current official About evidence describes contemporary women's "
            "apparel made from natural linen.",
        ),
        ("leather goods",),
    ),
    ObscureBrandCase(
        "NOOE",
        "nooe.co",
        ("workspace accessories", "stationery"),
        ("Premium designer workspace accessories and stationery.",),
    ),
    ObscureBrandCase(
        "Authenticity50",
        "authenticity50.com",
        ("american-made bedding", "home textiles"),
        ("American-made bedding and home textiles.",),
    ),
    ObscureBrandCase(
        "Atomicwork",
        "atomicwork.com",
        ("IT service management", "employee support"),
        ("An AI-native IT service management and employee-support platform.",),
    ),
    ObscureBrandCase(
        "Facets",
        "facets.cloud",
        ("infrastructure control plane", "internal developer platform"),
        ("An infrastructure control plane and internal developer platform.",),
    ),
    ObscureBrandCase(
        "Loop Health",
        "loophealth.com",
        ("employer health benefits", "group insurance"),
        ("Employer health benefits combining insurance and preventive care.",),
    ),
    ObscureBrandCase(
        "Airtribe",
        "airtribe.live",
        ("cohort", "professional upskilling"),
        ("Live cohort-based professional technology and product upskilling.",),
    ),
    ObscureBrandCase(
        "Kalungi",
        "kalungi.com",
        ("outsourced B2B SaaS marketing", "fractional CMO"),
        ("An outsourced B2B SaaS marketing team with fractional CMO delivery.",),
    ),
    ObscureBrandCase(
        "Kodo",
        "kodo.in",
        ("spend management", "procurement workflow"),
        ("A spend-management, intake-to-pay and procurement workflow platform.",),
    ),
)
