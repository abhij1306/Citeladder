from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from scripts import check_complexity


def _policy() -> dict:
    return {
        "format_version": 1,
        "roots": ["app"],
        "defaults": {"max_function_cc": 12, "max_module_loc": 800},
        "exceptions": {"functions": {}, "modules": {}},
    }


def _measurements(*, loc: int = 20, complexity: int = 3) -> dict:
    return {
        "app/example.py": {
            "loc": loc,
            "functions": {"Example.run": complexity},
        }
    }


def test_measure_counts_supported_branches_and_qualified_names(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """
class Example:
    async def run(self, a, b, c, values):
        assert a
        if a and b and c:
            for value in values:
                pass
        result = [value for value in values if value]
        match result:
            case []:
                return None
        return result
""",
        encoding="utf-8",
    )

    assert check_complexity.measure(source) == {"Example.run": 9}


def test_measure_folds_nested_functions_into_parent(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """
def outer(value):
    def inner():
        if value:
            return value
    return inner()
""",
        encoding="utf-8",
    )

    assert check_complexity.measure(source) == {"outer": 2}


def test_measure_keeps_worst_duplicate_qualified_name(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """
class Example:
    def run(self):
        if True:
            return 1

class Example:
    def run(self):
        return 1
""",
        encoding="utf-8",
    )

    assert check_complexity.measure(source) == {"Example.run": 2}


def test_collect_measures_all_python_modules_under_roots(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "one.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    cache = app / "__pycache__"
    cache.mkdir()
    (cache / "ignored.py").write_text("def ignored():\n    pass\n", encoding="utf-8")

    assert check_complexity.collect(backend=tmp_path, roots=("app",)) == {
        "app/one.py": {"loc": 2, "functions": {"one": 1}}
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda policy: policy.update(extra=True), "policy keys"),
        (lambda policy: policy.update(format_version=2), "format_version"),
        (lambda policy: policy.update(roots=[]), "roots"),
        (
            lambda policy: policy["defaults"].update(max_function_cc=True),
            "positive integer",
        ),
        (
            lambda policy: policy["exceptions"]["functions"].update(
                {"app/example.py::run": 12}
            ),
            "must exceed the default",
        ),
        (
            lambda policy: policy["exceptions"]["functions"].update(
                {"app/example.py:run": 14}
            ),
            "must use path.py::qualified_name",
        ),
    ],
)
def test_validate_policy_rejects_malformed_policy(mutate, message: str) -> None:
    policy = _policy()
    mutate(policy)

    with pytest.raises(check_complexity.PolicyError, match=message):
        check_complexity.validate_policy(policy)


def test_load_policy_reports_missing_and_invalid_json(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(check_complexity.PolicyError, match="missing policy"):
        check_complexity.load_policy(missing)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(check_complexity.PolicyError, match="invalid JSON"):
        check_complexity.load_policy(invalid)


def test_defaults_allow_limits_and_reject_regressions() -> None:
    policy = _policy()

    assert not check_complexity.check_measurements(
        _measurements(loc=800, complexity=12), policy
    )
    failures = check_complexity.check_measurements(
        _measurements(loc=801, complexity=13), policy
    )

    assert failures == [
        "app/example.py: LOC 801 exceeds ceiling 800",
        "app/example.py::Example.run: CC 13 exceeds ceiling 12",
    ]


def test_exceptions_supply_bounded_legacy_ceilings() -> None:
    policy = _policy()
    policy["exceptions"] = {
        "functions": {"app/example.py::Example.run": 15},
        "modules": {"app/example.py": 900},
    }

    assert not check_complexity.check_measurements(
        _measurements(loc=900, complexity=15), policy
    )
    failures = check_complexity.check_measurements(
        _measurements(loc=901, complexity=16), policy
    )

    assert failures[:2] == [
        "app/example.py: LOC 901 exceeds ceiling 900",
        "app/example.py::Example.run: CC 16 exceeds ceiling 15",
    ]


@pytest.mark.parametrize(
    ("measurements", "exception_kind", "exception", "message"),
    [
        ({}, "modules", "app/gone.py", "does not exist"),
        (_measurements(), "modules", "app/example.py", "within the default"),
        ({}, "functions", "app/gone.py::run", "does not exist"),
        (
            _measurements(),
            "functions",
            "app/example.py::Example.run",
            "within the default",
        ),
    ],
)
def test_stale_exceptions_fail(
    measurements: dict, exception_kind: str, exception: str, message: str
) -> None:
    policy = _policy()
    ceiling = 900 if exception_kind == "modules" else 14
    policy["exceptions"][exception_kind][exception] = ceiling

    assert any(
        message in failure
        for failure in check_complexity.check_measurements(measurements, policy)
    )


def test_policy_diff_allows_only_reductions_and_removals() -> None:
    base = _policy()
    base["exceptions"] = {
        "functions": {
            "app/example.py::Example.run": 16,
            "app/removed.py::run": 14,
        },
        "modules": {"app/example.py": 900},
    }
    current = json.loads(json.dumps(base))
    current["defaults"]["max_function_cc"] = 11
    current["exceptions"]["functions"]["app/example.py::Example.run"] = 15
    del current["exceptions"]["functions"]["app/removed.py::run"]
    current["exceptions"]["modules"]["app/example.py"] = 850
    # Widening the gate onto a tree it did not cover is a tightening, not a
    # relaxation, so it must pass the diff.
    current["roots"] = [*base["roots"], "scripts"]

    assert not check_complexity.compare_policies(base, current)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda policy: policy["defaults"].update(max_function_cc=13),
            "default max_function_cc increased",
        ),
        (lambda policy: policy.update(roots=["other"]), "application roots removed"),
        (
            lambda policy: policy["exceptions"]["functions"].update(
                {"app/example.py::Example.run": 17}
            ),
            "function exception.*increased",
        ),
        (
            lambda policy: policy["exceptions"]["functions"].update(
                {"app/new.py::run": 14}
            ),
            "new function exception is forbidden",
        ),
        (
            lambda policy: policy["exceptions"]["modules"].update({"app/new.py": 900}),
            "new module exception is forbidden",
        ),
    ],
)
def test_policy_diff_rejects_relaxations(mutate, message: str) -> None:
    base = _policy()
    base["exceptions"]["functions"]["app/example.py::Example.run"] = 16
    current = json.loads(json.dumps(base))
    mutate(current)

    assert any(
        re.search(message, failure)
        for failure in check_complexity.compare_policies(base, current)
    )


def test_policy_at_revision_permits_bootstrap_when_base_file_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        subprocess.CompletedProcess([], 0, b"a" * 40 + b" commit 1\n", b""),
        subprocess.CompletedProcess([], 0, b"HEAD:path missing\n", b""),
    ]
    monkeypatch.setattr(
        check_complexity.subprocess,
        "run",
        lambda *args, **kwargs: responses.pop(0),
    )

    assert check_complexity.policy_at_revision("HEAD") is None


def test_policy_at_revision_rejects_unknown_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = subprocess.CompletedProcess([], 0, b"missing missing\n", b"")
    monkeypatch.setattr(
        check_complexity.subprocess, "run", lambda *args, **kwargs: result
    )

    with pytest.raises(check_complexity.PolicyError, match="unknown base revision"):
        check_complexity.policy_at_revision("missing")


def test_policy_at_revision_fails_closed_when_git_cannot_read_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        subprocess.CompletedProcess([], 0, b"a" * 40 + b" commit 1\n", b""),
        subprocess.CompletedProcess([], 128, b"", b"fatal: object read failed"),
    ]
    monkeypatch.setattr(
        check_complexity.subprocess,
        "run",
        lambda *args, **kwargs: responses.pop(0),
    )

    with pytest.raises(check_complexity.PolicyError, match="fatal: object read failed"):
        check_complexity.policy_at_revision("HEAD")


def test_policy_at_revision_rejects_unsafe_revision_before_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_run(*args, **kwargs):
        pytest.fail("unsafe revisions must not reach git")

    monkeypatch.setattr(check_complexity.subprocess, "run", unexpected_run)

    with pytest.raises(check_complexity.PolicyError, match="unknown base revision"):
        check_complexity.policy_at_revision("HEAD;git status")


def test_main_checks_measurements_and_bootstrap_diff(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_complexity, "load_policy", _policy)
    monkeypatch.setattr(check_complexity, "collect", lambda **kwargs: _measurements())
    monkeypatch.setattr(check_complexity, "policy_at_revision", lambda revision: None)

    assert check_complexity.main(["--check-policy-diff", "HEAD"]) == 0
    assert "complexity policy ok" in capsys.readouterr().out


def test_main_rejects_policy_relaxation_from_base(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    current = _policy()
    base = _policy()
    current["defaults"]["max_function_cc"] = 13
    monkeypatch.setattr(check_complexity, "load_policy", lambda: current)
    monkeypatch.setattr(check_complexity, "collect", lambda **kwargs: _measurements())
    monkeypatch.setattr(check_complexity, "policy_at_revision", lambda revision: base)

    assert check_complexity.main(["--check-policy-diff", "HEAD"]) == 1
    assert "default max_function_cc increased 12 -> 13" in capsys.readouterr().err


def test_main_reports_policy_load_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_load() -> dict:
        raise check_complexity.PolicyError("invalid policy fixture")

    monkeypatch.setattr(check_complexity, "load_policy", fail_load)

    assert check_complexity.main([]) == 1
    assert "complexity policy error: invalid policy fixture" in capsys.readouterr().err


def test_main_returns_failure_for_policy_violation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_complexity, "load_policy", _policy)
    monkeypatch.setattr(
        check_complexity,
        "collect",
        lambda **kwargs: _measurements(complexity=13),
    )

    assert check_complexity.main([]) == 1
    assert "CC 13 exceeds ceiling 12" in capsys.readouterr().err
