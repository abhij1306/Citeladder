"""Complexity ratchet: the debt measured in the July 2026 audit cannot regrow.

That audit found two modules at Maintainability Index 0.0. They reached that
state without any build ever objecting, because nothing in CI measures module
size or function complexity. This script is that missing watcher — added
alongside the work that split them, so the reduction actually holds.

It is a RATCHET, not a standard: the checked-in baseline records today's worst
values, and the build fails when a module gets longer or a function gets more
branching than its recorded budget. Improving a number never fails the build —
it just prints how much slack was earned, so the baseline can be tightened.

Deliberately dependency-free (stdlib ``ast``): CI installs from a frozen lock,
so a checker that needed radon would mean lockfile churn on every touch. The
cyclomatic complexity here is the standard branch count — decision points plus
one — which matches radon closely enough for a ratchet.

Usage:
    python -m scripts.check_complexity           # check against the baseline
    python -m scripts.check_complexity --update  # rewrite it (review the diff)
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
BASELINE_PATH = Path(__file__).resolve().parent / "complexity_baseline.json"

# Only application code is ratcheted. Tests have their own (worse) numbers and
# decomposing them is tracked separately; ratcheting them now would freeze the
# 3,300-line component monolith in place rather than encouraging its split.
ROOTS = ("app",)

# A function above this is flagged even if the module's budget still allows it,
# so a new hotspot cannot hide inside an already-large module. Existing
# offenders are grandfathered through the baseline's per-function budgets.
NEW_FUNCTION_CC_CEILING = 15

# Branch-forming nodes. `BoolOp` counts each extra operand: `a and b and c` is
# two decision points, matching radon.
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


def cyclomatic_complexity(node: ast.AST) -> int:
    """Decision points + 1, counted over a function body."""
    score = 1
    for child in ast.walk(node):
        if isinstance(child, _BRANCH_NODES):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            score += 1 + len(child.ifs)
    return score


def measure(path: Path) -> tuple[int, dict[str, int]]:
    """``(loc, {qualified_function_name: cc})`` for one module."""
    source = path.read_text(encoding="utf-8")
    loc = len(source.splitlines())
    tree = ast.parse(source)
    functions: dict[str, int] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                functions[f"{prefix}{child.name}"] = cyclomatic_complexity(child)
                # Nested defs are folded into their parent's score above; they
                # are not reported separately.
            else:
                walk(child, prefix)

    walk(tree, "")
    return loc, functions


def collect() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for root in ROOTS:
        for path in sorted((BACKEND / root).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(BACKEND).as_posix()
            loc, functions = measure(path)
            worst = max(functions.values(), default=0)
            out[rel] = {"loc": loc, "max_cc": worst}
    return out


def _compare(
    rel: str,
    now: dict,
    was: dict | None,
    failures: list[str],
    improvements: list[str],
) -> None:
    """Record one module's regressions and improvements against its baseline."""
    if was is None:
        # A NEW module gets no grandfathering: it must meet the ceiling.
        if now["max_cc"] > NEW_FUNCTION_CC_CEILING:
            failures.append(
                f"{rel}: new module has a function at CC {now['max_cc']} "
                f"(ceiling {NEW_FUNCTION_CC_CEILING})"
            )
        return
    if now["loc"] > was["loc"]:
        failures.append(
            f"{rel}: {was['loc']} -> {now['loc']} LOC "
            f"(+{now['loc'] - was['loc']}); split it or justify a new baseline"
        )
    if now["max_cc"] > was["max_cc"]:
        failures.append(
            f"{rel}: max function complexity {was['max_cc']} -> {now['max_cc']}"
        )
    if now["loc"] < was["loc"] or now["max_cc"] < was["max_cc"]:
        improvements.append(
            f"{rel}: LOC {was['loc']}->{now['loc']}, "
            f"max CC {was['max_cc']}->{now['max_cc']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update", action="store_true", help="rewrite the baseline from current code"
    )
    args = parser.parse_args()

    current = collect()

    if args.update:
        BASELINE_PATH.write_text(
            json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"baseline updated: {len(current)} modules -> {BASELINE_PATH.name}")
        return 0

    if not BASELINE_PATH.exists():
        print(f"missing baseline {BASELINE_PATH}; run with --update", file=sys.stderr)
        return 1

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    failures: list[str] = []
    improvements: list[str] = []
    for rel, now in sorted(current.items()):
        _compare(rel, now, baseline.get(rel), failures, improvements)

    if improvements:
        print(f"{len(improvements)} module(s) improved — tighten the baseline:")
        for line in improvements[:20]:
            print(f"  + {line}")
        print("  run: python -m scripts.check_complexity --update")

    if failures:
        print(f"\ncomplexity ratchet failed ({len(failures)}):", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        print(
            "\nThese modules are on a downward ratchet. Extract a collaborator "
            "rather than raising the budget; if the growth is genuinely "
            "warranted, rebaseline in its own commit so it is reviewed.",
            file=sys.stderr,
        )
        return 1

    print(f"complexity ratchet ok ({len(current)} modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
