"""Validate CiteLadder's active documentation boundary.

The repository deliberately archives superseded product plans. This check keeps
new or resurrected documents from silently becoming competing implementation
authorities and verifies local Markdown links in the active tree.

Run from the repository root:

    python docs/validate_documentation.py
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PREFIX = "docs/archive/"

ACTIVE_EXACT = {
    "AGENTS.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "README.md",
    "Review.md",
    "docs/DEVELOPMENT.md",
    "docs/README.md",
    "docs/api-error-contract.md",
    "docs/architecture.md",
    "docs/backend-architecture.md",
    "docs/commerce-intelligence.md",
    "docs/design.md",
    "docs/documentation-index.md",
    "docs/frontend-architecture.md",
    "docs/integrations-traffic-analytics.md",
    "docs/invariants.md",
    "docs/visibility-prompt.md",
    "docs/security-fix.md",
    "docs/release-checklist.md",
    "docs/operations/aws-hosting-runbook.md",
    "docs/operations/razorpay-and-demo-owner-requirements.md",
    "docs/site-health.md",
    "docs/ui-component-system.md",
    "docs/validate_documentation.py",
    "docs/plans/citeladder-aeo-product-rebuild.md",
    "docs/plans/citeladder-onboarding-discovery-v7.md",
    "docs/plans/commerce-suite-atomic-rebuild.md",
    "docs/plans/commerce-ui-redesign.md",
    "docs/plans/commerce-suite-retirement-manifest.md",
    "docs/plans/site-health-measurement-cutover.md",
    "docs/plans/site-health-measurement-reliability-pr4.md",
    "docs/plans/site-health-correctness-and-debt-reduction.md",
    "docs/plans/CITELADDER_CONTENT_GENERATION_SIMPLIFIED_PLAN.md",
    "docs/plans/aeo-opportunity-loop.md",
    # Written (and re-written) by `next dev`; see the notice inside them and
    # `node_modules/next/dist/server/lib/generate-agent-files.js`. Deleting
    # them only re-creates an uncommitted change, so they are committed and
    # classified here rather than fought with.
    "frontend/AGENTS.md",
    "frontend/CLAUDE.md",
}
ACTIVE_PREFIXES = (
    "docs/design-system/",
    "docs/evaluations/",
    "backend/docs/",
    ".github/",
)
DOCUMENT_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
# Generated trees. None of these are repository documents, and all of them are
# git-ignored, so anything found inside is build output rather than authored
# content. `frontend/.next/` matters most: its `standalone/` bundle vendors a
# second node_modules whose symlinks raise PermissionError on Windows, which
# made this guard unrunnable on any machine with a built frontend. Playwright's
# `test-results/` writes `error-context.md` files, which otherwise get reported
# as unclassified authorities on every failed visual run.
SKIP_PREFIXES = (
    ".git/",
    # Scratch agent worktrees: full checkouts of the repo, so every archived
    # doc in them is re-scanned with its relative links resolving against a
    # tree that has no repo root. Ignored by git; ignored here too.
    ".aislop/",
    "node_modules/",
    ".venv/",
    "backend/.venv/",
    "frontend/node_modules/",
    "frontend/.next/",
    "frontend/out/",
    "frontend/build/",
    "frontend/dist/",
    "frontend/coverage/",
    "frontend/test-results/",
    "frontend/playwright-report/",
    "frontend/.playwright/",
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((?P<target>[^)]+)\)")


@dataclass(frozen=True)
class Issue:
    path: str
    message: str

    def render(self) -> str:
        return f"{self.path}: {self.message}"


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _is_active_document(path: Path) -> bool:
    rel = _relative(path)
    return rel in ACTIVE_EXACT or rel.startswith(ACTIVE_PREFIXES)


def _is_repository_document(path: Path) -> bool:
    rel = _relative(path)
    if rel.startswith(SKIP_PREFIXES) or rel.startswith(ARCHIVE_PREFIX):
        return False
    if path.suffix.lower() not in DOCUMENT_SUFFIXES:
        return False
    parts = Path(rel).parts
    return len(parts) == 1 or rel.startswith(("docs/", "backend/docs/", "frontend/"))


def _iter_files() -> Iterator[Path]:
    """Walk the repository, pruning skipped trees before touching them.

    `Path.rglob` descends into every directory and only then lets the caller
    filter, so a vendored `node_modules` under `frontend/.next/standalone/`
    gets stat'ed and raises `PermissionError` on Windows. Pruning in `os.walk`
    keeps the guard runnable on a machine with a built frontend, and skips a
    large amount of pointless I/O everywhere else.
    """
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = Path(dirpath).relative_to(ROOT).as_posix()
        prefix = "" if rel_dir == "." else f"{rel_dir}/"
        dirnames[:] = [
            name
            for name in dirnames
            if not f"{prefix}{name}/".startswith((*SKIP_PREFIXES, ARCHIVE_PREFIX))
        ]
        for name in filenames:
            yield Path(dirpath) / name


def _markdown_files() -> list[Path]:
    return sorted(path for path in _iter_files() if path.suffix.lower() == ".md")


# Link targets carrying any of these schemes are external references, not paths
# into this repository, so link validation skips them. Spelled as schemes rather
# than literal prefixes so this reads as the skip-list it is: nothing here is a
# URL the script fetches.
_EXTERNAL_LINK_SCHEMES = ("http", "https", "mailto", "tel", "data")


def _link_path(source: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().strip("<>")
    if not target or target.startswith("#"):
        return None
    scheme, separator, _ = target.partition(":")
    if separator and scheme.lower() in _EXTERNAL_LINK_SCHEMES:
        return None
    # Optional Markdown title follows a whitespace boundary. Paths in this
    # repository do not intentionally contain unescaped spaces.
    target = target.split(maxsplit=1)[0]
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    if target.startswith("/"):
        return ROOT / target.lstrip("/")
    return (source.parent / target).resolve()


def validate() -> list[Issue]:
    issues: list[Issue] = []

    forbidden_active_dirs = (ROOT / "docs/roadmap",)
    for directory in forbidden_active_dirs:
        if directory.exists():
            issues.append(
                Issue(
                    _relative(directory), "superseded documentation directory is active"
                )
            )

    for path in sorted(_iter_files()):
        if not _is_repository_document(path):
            continue
        if not _is_active_document(path):
            issues.append(
                Issue(
                    _relative(path),
                    "unclassified active document; add it to the authority "
                    "map or archive it",
                )
            )

    for source in _markdown_files():
        text = source.read_text(encoding="utf-8", errors="replace")
        for match in MARKDOWN_LINK.finditer(text):
            resolved = _link_path(source, match.group("target"))
            if resolved is None:
                continue
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                issues.append(
                    Issue(
                        _relative(source),
                        f"local link escapes repository: {match.group('target')!r}",
                    )
                )
                continue
            if not resolved.exists():
                issues.append(
                    Issue(
                        _relative(source),
                        f"broken local link: {match.group('target')!r}",
                    )
                )

    canonical = ROOT / "docs/documentation-index.md"
    if canonical.is_file():
        index_text = canonical.read_text(encoding="utf-8", errors="replace")
        required_fragments = (
            "architecture.md",
            "citeladder-aeo-product-rebuild.md",
            "site-health.md",
        )
        for required in required_fragments:
            if required not in index_text:
                issues.append(
                    Issue(
                        _relative(canonical),
                        f"authority index does not reference {required}",
                    )
                )

    return issues


def main() -> int:
    issues = validate()
    if issues:
        print("Documentation validation failed:", file=sys.stderr)
        for issue in issues:
            print(f"- {issue.render()}", file=sys.stderr)
        return 1
    active_count = sum(
        1
        for path in _iter_files()
        if _is_repository_document(path) and _is_active_document(path)
    )
    archived_count = sum(
        1 for path in (ROOT / "docs/archive").rglob("*") if path.is_file()
    )
    print(
        f"Documentation boundary valid: {active_count} active documents, "
        f"{archived_count} archived files."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
