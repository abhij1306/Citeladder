# Site Health Correctness and Onboarding Debt Reduction

## Summary

This plan is the approved implementation authority for the Site Health
correctness, issue-evidence, desktop workspace, and immediate onboarding-shell
work. Slice 1 freezes an HTTP-only 50-URL audit before any detector or database
changes. The onboarding completion invariant is at-least-once task dispatch
with exactly-once persisted completion effect; no external broker or outbox is
introduced.

## Slice 1 — frozen audit

- Use the latest completed or partially completed crawl for Goodee, Lootcrate,
  Potgang, and United By Blue. Exclude Cocofloss.
- Select exactly 50 URLs: 12 per company using alternating lowest Web/AEO
  score streams, then two global lowest-score URLs, prioritizing distinct page
  kinds and deterministic URL tie-breakers.
- Fetch each URL once through the existing SSRF-safe `SecureFetcher`, with no
  JavaScript. Keep raw bodies and redacted headers only in gitignored
  `artifacts/site-health-audit/<run-id>/`; commit hashes and bounded reports.
- Review every persisted issue occurrence as `verified` or `wrong` from the
  frozen response, and record HTTP-visible missed findings separately.
- Save the dated report, occurrence CSV, missed-finding CSV, and fixture
  manifest under `docs/evaluations/`. Re-run the exact frozen corpus after
  detector fixes to compare false-positive and false-negative rates.

## Correctness and issue evidence

- Rewrite inverted issue subtitles as failure-specific statements and retain
  remediation separately.
- Use existing parser boundaries for full-document and primary-content
  headings. Name the signals **Web — Full-document heading hierarchy** and
  **AEO — Primary-content heading hierarchy**; report exact transitions (for
  example, `H1 → H3, primary content`) as structural signals, not automatic
  accessibility violations.
- Correct accessible-name detection for ARIA, labels, native names, title
  fallback, and hidden/inert/template exclusion; retain bounded offending
  control descriptors.
- Preserve exact schema expected/found types and missing property paths.
- Expose one occurrence-backed evidence model: catalog `group_id`, persisted
  `occurrence_id`, and direct `evaluation_id`. Do not join page evidence by
  `rule_id`; remove duplicated group-level canonical evidence.
- Replace stacked issue cards with one responsive master-detail workspace and
  one shared evidence presenter for issue and URL detail.

## Immediate onboarding shell

Persist project shell, discovery linkage, empty prompt set, and deterministic
existing PostgreSQL completion task in one short transaction, then commit and
return `202` with `project_id`. The task row is the PostgreSQL queue: workers
cannot observe it before commit, and rollback leaves no shell or task. Repeated
completion requests lock the discovery and ensure the same deterministic task
identity. Leases permit at-least-once worker execution; uniqueness and one
transaction around prompt insertion plus terminal transition provide exactly
one effective completion. The project opens immediately while prompts run.

No new table, queue, lifecycle state, outbox, broker, or compatibility evidence
representation is allowed. Complexity-policy counts and removal of duplicate
owners are architectural gates. LOC reduction is a strong target only and
must not be achieved through statement compression, collapsed abstractions,
hidden complexity, or removal of acceptance behavior.

## Acceptance

- The frozen corpus has 50 selected URLs, one acquisition record per URL,
  binary verdicts for all reported occurrences, and bounded missed findings.
- Parser/rule fixtures cover controls, both heading scopes, exact schema
  evidence, and deterministic replay.
- API/UI tests cover workspace isolation, direct occurrence/evaluation linkage,
  one evidence owner, responsive master-detail behavior, and per-page detail.
- Two simultaneous completion requests return one project and one effective
  prompt portfolio; rollback, lease recovery, and terminal replay are covered.
- Final validation runs `scripts/check.ps1` followed by `scripts/test.ps1`.
