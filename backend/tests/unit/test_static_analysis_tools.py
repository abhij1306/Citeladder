"""Regression fixtures for the pinned static-analysis toolchain.

Two kinds of test live here. The first checks that a tool still detects what it
is gated for. The second checks the GATE CONFIGURATION itself -- that the scope
has not narrowed, a rule family has not been dropped, and a suppression has not
become blanket. Weakening a gate should take an explicit decision, not a quiet
edit to a config file nobody reads.
"""

from __future__ import annotations

import configparser
import json
import re
import tomllib
from pathlib import Path

from vulture import Vulture

BACKEND = Path(__file__).resolve().parents[2]


def test_vulture_gate_detects_a_high_confidence_unused_import() -> None:
    scanner = Vulture()
    scanner.scan("import os\n", filename="fixture.py")

    findings = scanner.get_unused_code(min_confidence=80)

    observed = [(finding.name, finding.confidence, finding.typ) for finding in findings]
    assert observed == [("os", 90, "import")]


def _pyproject() -> dict:
    with (BACKEND / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


class TestSuppressionGate:
    """`# noqa` comments must suppress something real.

    An audit found 22 directives that suppressed nothing: two file-level
    `# ruff: noqa: E501` blankets on files with no long lines, eleven stale
    `B008`s, and nine naming rules this config has never enabled. Each read as a
    reviewed exception. RUF100 is what makes that impossible; these tests stop
    it being switched off or narrowed away.
    """

    def test_ruff_selects_the_unused_noqa_rule(self) -> None:
        lint = _pyproject()["tool"]["ruff"]["lint"]

        # RUF100 arrives via the "RUF" family.
        assert "RUF" in lint["select"]
        assert "RUF100" not in lint.get("ignore", [])

    def test_no_blanket_per_file_ignore_covers_application_code(self) -> None:
        per_file = _pyproject()["tool"]["ruff"]["lint"].get("per-file-ignores", {})

        for pattern, codes in per_file.items():
            assert pattern.startswith(("tests/", "evaluations/")), (
                f"{pattern} exempts application code from {codes}; suppress at "
                "the line with a reason instead"
            )

    def test_security_and_async_families_are_gated(self) -> None:
        select = _pyproject()["tool"]["ruff"]["lint"]["select"]

        # S catches insecure hashes/deserialization/subprocess use, ASYNC
        # catches blocking calls inside coroutines, BLE catches blind excepts.
        assert {"S", "ASYNC", "BLE"} <= set(select)


class TestGateScope:
    """Every Python tree ships or is operated; all of them are gated."""

    def test_mypy_checks_scripts_and_evaluations(self) -> None:
        files = _pyproject()["tool"]["mypy"]["files"]

        assert set(files) == {"app", "evaluations", "scripts"}

    def test_complexity_policy_covers_the_same_trees(self) -> None:
        with (BACKEND / "scripts/complexity_policy.json").open(
            encoding="utf-8"
        ) as handle:
            policy = json.load(handle)

        assert set(policy["roots"]) == {"app", "evaluations", "scripts"}
        # The ceilings are fixed and the exception lists stay empty; a
        # regression is refactored, never budgeted.
        assert policy["defaults"] == {"max_function_cc": 12, "max_module_loc": 800}
        assert policy["exceptions"] == {"functions": {}, "modules": {}}


class TestArchitecturePolicy:
    """`.importlinter` is the backend counterpart to `pnpm check:policy`."""

    def _contracts(self) -> dict[str, dict[str, str]]:
        parser = configparser.ConfigParser()
        parser.read(BACKEND / ".importlinter", encoding="utf-8")
        return {
            section.split(":")[-1]: dict(parser[section])
            for section in parser.sections()
            if section.startswith("importlinter:contract:")
        }

    def test_every_expected_contract_is_declared(self) -> None:
        assert set(self._contracts()) == {
            "api-is-a-leaf",
            "workers-are-a-leaf",
            "core-is-the-floor",
            "models-are-persistence-only",
            "connectors-are-transport-only",
            "orchestration-is-infrastructure",
            "analysis-does-not-reach-up",
        }

    def test_the_two_leaf_contracts_are_checked_transitively(self) -> None:
        """These hold for every import path, not just direct ones.

        `allow_indirect_imports` is the weaker mode, needed only where a chain
        runs through an edge this policy deliberately allows. The leaf
        contracts do not need it and must not acquire it.
        """
        contracts = self._contracts()

        for name in ("api-is-a-leaf", "workers-are-a-leaf", "core-is-the-floor"):
            assert "allow_indirect_imports" not in contracts[name]

    def test_recorded_exceptions_stay_at_three(self) -> None:
        """Named warts, not a widening rule. Adding a fourth is a decision."""
        ignored = [
            line.strip()
            for contract in self._contracts().values()
            for line in contract.get("ignore_imports", "").splitlines()
            if line.strip()
        ]

        assert sorted(ignored) == [
            "app.connectors.answer_engines.normalization -> app.analysis.normalization",
            "app.connectors.web_evidence.brand_evidence"
            " -> app.analysis.site_health.dom",
            "app.models.prompt -> app.domain.prompts.normalization",
        ]


class TestDependencyHygiene:
    def test_every_deptry_exception_is_a_declared_dependency(self) -> None:
        """A DEP002 ignore for a dependency that no longer exists is dead.

        Without this, removing a dependency leaves its exception behind to
        silently cover the next package that happens to share the name.
        """
        config = _pyproject()
        declared = {
            re.split(r"[<>=!~\[ ]", item)[0].lower()
            for group in (
                config["project"]["dependencies"],
                config["project"]["optional-dependencies"]["dev"],
            )
            for item in group
        }
        ignored = config["tool"]["deptry"]["per_rule_ignores"]["DEP002"]

        assert {name.lower() for name in ignored} <= declared


class TestCoverageGate:
    def test_changed_line_coverage_is_configured(self) -> None:
        """The gate is diff coverage, not a repository-wide floor.

        The CI comment used to claim a `[tool.coverage.report] fail_under` that
        was never set, so coverage gated nothing at all.
        """
        config = _pyproject()

        assert config["tool"]["diff_cover"]["fail_under"] == 90
        assert "fail_under" not in config["tool"]["coverage"]["report"]
