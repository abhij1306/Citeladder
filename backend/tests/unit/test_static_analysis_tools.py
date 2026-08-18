"""Regression fixtures for the pinned static-analysis toolchain."""

from vulture import Vulture


def test_vulture_gate_detects_a_high_confidence_unused_import() -> None:
    scanner = Vulture()
    scanner.scan("import os\n", filename="fixture.py")

    findings = scanner.get_unused_code(min_confidence=80)

    observed = [(finding.name, finding.confidence, finding.typ) for finding in findings]
    assert observed == [("os", 90, "import")]
