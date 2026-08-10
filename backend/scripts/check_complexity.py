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
import re
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
_BASE_REVISION_PATTERN = re.compile(r"(?:HEAD|[0-9a-fA-F]{40})\Z")


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


def _validate_roots(roots: object) -> None:
    if (
        not isinstance(roots, list)
        or not roots
        or any(not isinstance(root, str) or not root for root in roots)
        or len(set(roots)) != len(roots)
    ):
        raise PolicyError("roots must be a non-empty list of unique strings")


def _validate_defaults(defaults: object) -> tuple[int, int]:
    if not isinstance(defaults, dict) or set(defaults) != _DEFAULT_KEYS:
        raise PolicyError(f"defaults keys must be exactly {sorted(_DEFAULT_KEYS)}")
    return (
        _positive_integer(defaults["max_function_cc"], "defaults.max_function_cc"),
        _positive_integer(defaults["max_module_loc"], "defaults.max_module_loc"),
    )


def _validate_exception_entries(entries: object, *, kind: str, default: int) -> None:
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
        raise PolicyError("function exception keys must use path.py::qualified_name")


def _validate_exceptions(
    exceptions: object, *, function_default: int, module_default: int
) -> None:
    if not isinstance(exceptions, dict) or set(exceptions) != _EXCEPTION_KEYS:
        raise PolicyError(f"exceptions keys must be exactly {sorted(_EXCEPTION_KEYS)}")
    _validate_exception_entries(
        exceptions["functions"], kind="functions", default=function_default
    )
    _validate_exception_entries(
        exceptions["modules"], kind="modules", default=module_default
    )


def validate_policy(raw: object) -> dict[str, Any]:
    """Validate and return a normalized policy mapping."""
    if not isinstance(raw, dict) or set(raw) != _POLICY_KEYS:
        raise PolicyError(f"policy keys must be exactly {sorted(_POLICY_KEYS)}")
    if raw["format_version"] != 1:
        raise PolicyError("format_version must be 1")

    _validate_roots(raw["roots"])
    function_default, module_default = _validate_defaults(raw["defaults"])
    _validate_exceptions(
        raw["exceptions"],
        function_default=function_default,
        module_default=module_default,
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


def _measurement_limit_failures(
    measurements: dict[str, dict[str, Any]],
    *,
    defaults: dict[str, int],
    function_exceptions: dict[str, int],
    module_exceptions: dict[str, int],
) -> list[str]:
    failures: list[str] = []
    for relative_path, module in sorted(measurements.items()):
        loc = module["loc"]
        loc_ceiling = module_exceptions.get(relative_path, defaults["max_module_loc"])
        if loc > loc_ceiling:
            failures.append(f"{relative_path}: LOC {loc} exceeds ceiling {loc_ceiling}")
        for name, complexity in module["functions"].items():
            key = f"{relative_path}::{name}"
            cc_ceiling = function_exceptions.get(key, defaults["max_function_cc"])
            if complexity > cc_ceiling:
                failures.append(f"{key}: CC {complexity} exceeds ceiling {cc_ceiling}")
    return failures


def _stale_module_exception_failures(
    measurements: dict[str, dict[str, Any]],
    *,
    default: int,
    exceptions: dict[str, int],
) -> list[str]:
    failures: list[str] = []
    for relative_path in sorted(exceptions):
        module = measurements.get(relative_path)
        if module is None:
            failures.append(f"stale module exception: {relative_path} does not exist")
        elif module["loc"] <= default:
            failures.append(
                f"stale module exception: {relative_path} is now within the default"
            )
    return failures


def _stale_function_exception_failures(
    measurements: dict[str, dict[str, Any]],
    *,
    default: int,
    exceptions: dict[str, int],
) -> list[str]:
    failures: list[str] = []
    for key in sorted(exceptions):
        relative_path, separator, name = key.partition("::")
        module = measurements.get(relative_path)
        if not separator or module is None or name not in module["functions"]:
            failures.append(f"stale function exception: {key} does not exist")
        elif module["functions"][name] <= default:
            failures.append(
                f"stale function exception: {key} is now within the default"
            )
    return failures


def check_measurements(
    measurements: dict[str, dict[str, Any]], policy: dict[str, Any]
) -> list[str]:
    """Return violations, including obsolete or missing exception targets."""
    defaults: dict[str, int] = policy["defaults"]
    exceptions = policy["exceptions"]
    function_exceptions: dict[str, int] = exceptions["functions"]
    module_exceptions: dict[str, int] = exceptions["modules"]
    failures = _measurement_limit_failures(
        measurements,
        defaults=defaults,
        function_exceptions=function_exceptions,
        module_exceptions=module_exceptions,
    )
    failures.extend(
        _stale_module_exception_failures(
            measurements,
            default=defaults["max_module_loc"],
            exceptions=module_exceptions,
        )
    )
    failures.extend(
        _stale_function_exception_failures(
            measurements,
            default=defaults["max_function_cc"],
            exceptions=function_exceptions,
        )
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
    if _BASE_REVISION_PATTERN.fullmatch(base_revision) is None:
        raise PolicyError(f"unknown base revision: {base_revision}")

    # Keep the OS command itself constant. Object expressions are supplied through
    # Git's documented batch protocol only after the strict validation above.
    revision = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        cwd=REPOSITORY,
        input=f"{base_revision}^{{commit}}\n".encode(),
        capture_output=True,
        check=False,
    )
    if revision.returncode != 0 or revision.stdout.rstrip().endswith(b" missing"):
        raise PolicyError(f"unknown base revision: {base_revision}")

    result = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=REPOSITORY,
        input=f"{base_revision}:{POLICY_REPOSITORY_PATH}\n".encode(),
        capture_output=True,
        check=False,
    )
    header, separator, payload = result.stdout.partition(b"\n")
    if result.returncode != 0 or header.endswith(b" missing"):
        return None
    header_parts = header.split()
    if not separator or len(header_parts) != 3 or header_parts[1] != b"blob":
        raise PolicyError("base policy is not a readable Git blob")
    try:
        size = int(header_parts[2])
        raw = payload[:size].decode("utf-8")
        return validate_policy(json.loads(raw))
    except ValueError as error:
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
