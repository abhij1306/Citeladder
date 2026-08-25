"""The one owner of which ``.env`` files settings may read.

Every ``BaseSettings`` class in this package reads the repo-root and
backend-local ``.env`` so a developer can configure the stack without exporting
anything. That is right for a running process and wrong for a test run.

A developer ``.env`` carries real secrets: provider API keys, OAuth client
secrets, the Fernet encryption key, a live database password. When the test
suite imports the app, every one of those loads into the settings singletons,
and any code path gated on "is this provider configured?" turns ON. That is not
hypothetical — a component test for the agent worker built a live gateway and
posted evidence to a real provider endpoint, because the developer's key made
``default_agent_settings.configured`` true.

So tests never read ``.env``. ``backend/tests/conftest.py`` sets
``CITELADDER_DISABLE_DOTENV`` before importing anything from ``app`` and then
supplies its own deterministic values through the process environment, which
pydantic-settings still reads. The result is a suite whose configuration is
declared in the repository rather than inherited from whoever is running it:
the same on a laptop, in CI, and in review.

This is deliberately an explicit opt-out rather than pytest auto-detection.
Auto-detection would silently change how production code loads configuration
based on what imported it, and a non-pytest harness (a script, a notebook, a
future runner) would get no protection at all.
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/app/core/config/dotenv.py -> parents[3] == backend/
BASE_DIR = Path(__file__).resolve().parents[3]
PROJECT_ROOT = BASE_DIR.parent

DISABLE_DOTENV_VAR = "CITELADDER_DISABLE_DOTENV"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def dotenv_disabled() -> bool:
    """Whether ``.env`` loading is switched off for this process."""
    return os.environ.get(DISABLE_DOTENV_VAR, "").strip().casefold() in _TRUTHY


def dotenv_sources() -> tuple[str, ...] | None:
    """The ``env_file`` value every settings class in this package must use.

    Returns ``None`` — pydantic-settings' "read no file at all" — when
    ``CITELADDER_DISABLE_DOTENV`` is set. The process environment is still read
    in both cases, so an explicit export always wins and a test can configure
    exactly what it needs.
    """
    if dotenv_disabled():
        return None
    return (str(PROJECT_ROOT / ".env"), str(BASE_DIR / ".env"))
