# Technical debt baseline — 2026-08-18

This is the reproducible starting point for the six-PR production-debt program. It is
an evaluation artifact, not permission to relax the checked-in policies. Commands and
versions are owned by `docs/DEVELOPMENT.md` and the frozen package locks.

## Tooling and measured debt

| Signal | Baseline | Policy |
|---|---:|---|
| Backend AST policy | 412 modules; 77 function and 21 module exceptions | CC 12 and 800 LOC; base-diff rejects new or larger exceptions |
| Vulture 2.16 | zero findings at confidence 80 | blocking at confidence 80; lower-confidence framework findings remain review-only |
| Radon 6.0.1 | 228 functions at CC >= 10; lowest MI: Opportunities service and Site Health parser | CC/MI report is advisory; the repository AST checker is authoritative |
| jscpd 5.0.11 production scope | 6 accepted clones; 0.07% duplicated lines | new fingerprints or a higher aggregate percentage fail |
| Frontend policy | 49 function and 13 module exceptions | CC 12; 500 production LOC; 800 test LOC; base-diff rejects new or larger exceptions |

The largest backend owners are Site Health config (2,552 LOC), Opportunities service
(2,061), audit planner (1,720), audit worker (1,605), and Site Health models (1,427).
The largest frontend production owners are the Site Health schema catalog and the
Dashboard, marketing preview, Content, Onboarding, Traffic, and URL-detail surfaces.

## Exception ownership and removal conditions

The JSON policy files are the exact symbol/file ledgers. Their removal sequence is:

- Site Health, Billing, and Integrations config plus Site Health models: PR 2, after
  import and SQLAlchemy metadata characterization.
- Opportunities, audit planning, Traffic, Commerce, Attribution, Products, Prompts,
  Analysis, and Projects domain exceptions: PR 3, after behavior/workspace/provenance
  characterization.
- Worker, acquisition, parser/rule, and API exceptions: PR 4, after lease, retry,
  security, version, and error-contract characterization.
- Every frontend function/module exception: PR 5, after route, state, API-schema, and
  focused Vitest characterization. No frontend exception survives the program.

An exception may be removed earlier when its measured owner falls within the default.
It may not be renamed, enlarged, or replaced with another exception.

## Accepted production clone fingerprints

| Clone family | Classification | Owner and removal condition |
|---|---|---|
| Analytics/Discovery/Integrations/Site Health model task fields | Domain-distinct SQLAlchemy boilerplate | Persistence owners; review in PR 2 and retain only if a mixin would obscure table, constraint, or queue semantics |
| Audit/Content immutable-attempt fields | Domain-distinct SQLAlchemy boilerplate | Audit and Content persistence owners; same PR 2 criterion |
| Product and Prompt CSV dialogs | Actionable UI workflow duplication | Remove in PR 5 after both import contracts have focused tests |
| Opportunity implementation/verification schema blocks | Same-owner contract repetition | Review in PR 3/5; consolidate only if discriminated wire shapes remain explicit |

Tests are scanned separately as an advisory debt signal. Coverage percentages are not a
program gate; behavior-focused characterization and the repository's existing full suites
remain the acceptance evidence.
