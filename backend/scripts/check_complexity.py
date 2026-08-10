"""Enforce stable complexity and module-size ceilings for backend application code.

The policy is intentionally small and hand-maintained. Every function and module
uses the fixed defaults unless it has a named legacy exception. Exceptions carry
bounded headroom and disappear once the code reaches the default; there is no
whole-repository update command that can silently turn regressions into budgets.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent
REPOSITORY = BACKEND.parent
POLICY_PATH = Path(__file__).resolve().parent / "complexity_policy.json"
POLICY_REPOSITORY_PATH = "backend/scripts/complexity_policy.json"

_BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.Assert,
    ast.IfExp,
    ast.Match,
)
_POLICY_KEYS = {"format_version", "roots", "defaults", "exceptions"}
_DEFAULT_KEYS = {"max_function_cc", "max_module_loc"}
_EXCEPTION_KEYS = {"functions", "modules"}


class PolicyError(ValueError):
    """The checked-in complexity policy is malformed."""


def cyclomatic_complexity(node: ast.AST) -> int:
    """Return decision points plus one for a function AST."""
    score = 1
    for child in ast.walk(node):
        if isinstance(child, _BRANCH_NODES):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            score += 1 + len(child.ifs)
    return score


def measure(path: Path) -> dict[str, int]:
    """Return qualified function names and their complexity for one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions: dict[str, int] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                name = f"{prefix}{child.name}"
                functions[name] = max(
                    cyclomatic_complexity(child), functions.get(name, 0)
                )
                # Nested functions are already folded into their parent's score.
            else:
                walk(child, prefix)

    walk(tree, "")
    return functions


def collect(
    *, backend: Path = BACKEND, roots: tuple[str, ...] = ("app",)
) -> dict[str, dict[str, Any]]:
    """Measure every Python module below the configured application roots."""
    measurements: dict[str, dict[str, Any]] = {}
    for root in roots:
        for path in sorted((backend / root).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative_path = path.relative_to(backend).as_posix()
            functions = measure(path)
            measurements[relative_path] = {
                "loc": len(path.read_text(encoding="utf-8").splitlines()),
                "functions": dict(sorted(functions.items())),
            }
    return measurements


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PolicyError(f"{label} must be a positive integer")
    return value


def validate_policy(raw: object) -> dict[str, Any]:
    """Validate and return a normalized policy mapping."""
    if not isinstance(raw, dict) or set(raw) != _POLICY_KEYS:
        raise PolicyError(f"policy keys must be exactly {sorted(_POLICY_KEYS)}")
    if raw["format_version"] != 1:
        raise PolicyError("format_version must be 1")

    roots = raw["roots"]
    if (
        not isinstance(roots, list)
        or not roots
        or any(not isinstance(root, str) or not root for root in roots)
        or len(set(roots)) != len(roots)
    ):
        raise PolicyError("roots must be a non-empty list of unique strings")

    defaults = raw["defaults"]
    if not isinstance(defaults, dict) or set(defaults) != _DEFAULT_KEYS:
        raise PolicyError(f"defaults keys must be exactly {sorted(_DEFAULT_KEYS)}")
    function_default = _positive_integer(
        defaults["max_function_cc"], "defaults.max_function_cc"
    )
    module_default = _positive_integer(
        defaults["max_module_loc"], "defaults.max_module_loc"
    )

    exceptions = raw["exceptions"]
    if not isinstance(exceptions, dict) or set(exceptions) != _EXCEPTION_KEYS:
        raise PolicyError(
            f"exceptions keys must be exactly {sorted(_EXCEPTION_KEYS)}"
        )
    for kind, default in (("functions", function_default), ("modules", module_default)):
        entries = exceptions[kind]
        if not isinstance(entries, dict):
            raise PolicyError(f"exceptions.{kind} must be an object")
        for name, ceiling in entries.items():
            if not isinstance(name, str) or not name:
                raise PolicyError(f"exceptions.{kind} keys must be non-empty strings")
            parsed_ceiling = _positive_integer(ceiling, f"exceptions.{kind}.{name}")
            if parsed_ceiling <= default:
                raise PolicyError(
                    f"exceptions.{kind}.{name} must exceed the default {default}"
                )
        if kind == "functions" and any("::" not in name for name in entries):
            raise PolicyError(
                "function exception keys must use path.py::qualified_name"
            )

    return raw


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    """Load and validate a policy JSON file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise PolicyError(f"missing policy: {path}") from error
    except json.JSONDecodeError as error:
        raise PolicyError(f"invalid JSON in {path}: {error}") from error
    return validate_policy(raw)


def check_measurements(
    measurements: dict[str, dict[str, Any]], policy: dict[str, Any]
) -> list[str]:
    """Return violations, including obsolete or missing exception targets."""
    defaults = policy["defaults"]
    exceptions = policy["exceptions"]
    function_exceptions: dict[str, int] = exceptions["functions"]
    module_exceptions: dict[str, int] = exceptions["modules"]
    failures: list[str] = []

    for relative_path, module in sorted(measurements.items()):
        loc = module["loc"]
        loc_ceiling = module_exceptions.get(
            relative_path, defaults["max_module_loc"]
        )
        if loc > loc_ceiling:
            failures.append(
                f"{relative_path}: LOC {loc} exceeds ceiling {loc_ceiling}"
            )
        for name, complexity in module["functions"].items():
            key = f"{relative_path}::{name}"
            cc_ceiling = function_exceptions.get(
                key, defaults["max_function_cc"]
            )
            if complexity > cc_ceiling:
                failures.append(
                    f"{key}: CC {complexity} exceeds ceiling {cc_ceiling}"
                )

    for relative_path in sorted(module_exceptions):
        module = measurements.get(relative_path)
        if module is None:
            failures.append(f"stale module exception: {relative_path} does not exist")
        elif module["loc"] <= defaults["max_module_loc"]:
            failures.append(
                f"stale module exception: {relative_path} is now within the default"
            )

    for key in sorted(function_exceptions):
        relative_path, separator, name = key.partition("::")
        module = measurements.get(relative_path)
        if not separator or module is None or name not in module["functions"]:
            failures.append(f"stale function exception: {key} does not exist")
        elif module["functions"][name] <= defaults["max_function_cc"]:
            failures.append(
                f"stale function exception: {key} is now within the default"
            )

    return failures


def compare_policies(base: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Reject every policy relaxation relative to an existing base policy."""
    failures: list[str] = []
    if current["format_version"] != base["format_version"]:
        failures.append("format_version changed")
    if current["roots"] != base["roots"]:
        failures.append("application roots changed")

    for name in sorted(_DEFAULT_KEYS):
        old = base["defaults"][name]
        new = current["defaults"][name]
        if new > old:
            failures.append(f"default {name} increased {old} -> {new}")

    for kind in sorted(_EXCEPTION_KEYS):
        old_entries = base["exceptions"][kind]
        new_entries = current["exceptions"][kind]
        for name, new in sorted(new_entries.items()):
            old = old_entries.get(name)
            if old is None:
                failures.append(f"new {kind[:-1]} exception is forbidden: {name}")
            elif new > old:
                failures.append(
                    f"{kind[:-1]} exception {name} increased {old} -> {new}"
                )
    return failures


def policy_at_revision(base_revision: str) -> dict[str, Any] | None:
    """Read the base policy; absence permits the repository's one bootstrap."""
    revision = subprocess.run(
        ["git", "cat-file", "-e", f"{base_revision}^{{commit}}"],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        check=False,
    )
    if revision.returncode != 0:
        raise PolicyError(f"unknown base revision: {base_revision}")
    result = subprocess.run(
        ["git", "show", f"{base_revision}:{POLICY_REPOSITORY_PATH}"],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return validate_policy(json.loads(result.stdout))
    except json.JSONDecodeError as error:
        raise PolicyError(f"base policy contains invalid JSON: {error}") from error


def _print_failures(title: str, failures: list[str]) -> None:
    print(f"{title} ({len(failures)}):", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-policy-diff",
        metavar="BASE_REV",
        help="reject policy relaxations relative to BASE_REV",
    )
    args = parser.parse_args(argv)

    try:
        policy = load_policy()
        measurements = collect(roots=tuple(policy["roots"]))
        failures = check_measurements(measurements, policy)
        if args.check_policy_diff:
            base = policy_at_revision(args.check_policy_diff)
            if base is not None:
                failures.extend(compare_policies(base, policy))
    except PolicyError as error:
        print(f"complexity policy error: {error}", file=sys.stderr)
        return 1

    if failures:
        _print_failures("complexity policy failed", failures)
        return 1
    print(
        "complexity policy ok "
        f"({len(measurements)} modules, "
        f"{len(policy['exceptions']['functions'])} function exceptions, "
        f"{len(policy['exceptions']['modules'])} module exceptions)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
