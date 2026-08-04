"""Compatibility import surface for the reliability-first onboarding package."""

from app.domain.projects.onboarding.service import (
    BrandDiscoveryError,
    complete_discovery,
    create_discovery,
    discovery_catalog,
    get_discovery,
    process_discovery,
)

__all__ = [
    "BrandDiscoveryError",
    "complete_discovery",
    "create_discovery",
    "discovery_catalog",
    "get_discovery",
    "process_discovery",
]
