# API Error Contract — CiteLadder

> The canonical, end-to-end contract for **how a CiteLadder API call fails**: the wire
> envelope every non-2xx response carries, how the backend produces it, and how the
> frontend consumes it. Companion docs: [`AGENTS.md`](../AGENTS.md),
> [`invariants.md`](invariants.md), [`backend-architecture.md`](backend-architecture.md)
> (§6 subsystem ownership), [`frontend-architecture.md`](frontend-architecture.md) (§6
> drift policy).

One owner per concept (invariant 2): the envelope is **produced** only by
`backend/app/core/errors.py`; on the frontend, `frontend/lib/api/client.ts` owns
**parsing** the wire envelope and `frontend/lib/api/errors.ts` owns the `ApiError`
type and its display-safe projection (`humanizeApiError`). Codes live in
`backend/app/core/config/errors.py` (invariant 1) — never inline.

## 1. The wire envelope

Every non-2xx response — from a router raise, a validation failure, a Starlette routing
404, or an unhandled crash — carries exactly this shape:

```jsonc
{
  "detail": "Crawl not found",          // legacy field, retained verbatim
  "error": {
    "code": "not_found",                // stable snake_case machine code
    "message": "Crawl not found",       // human sentence, safe to display
    "request_id": "018f…",              // correlation id for support
    "retryable": false,                 // server-side classification
    "details": { }                      // optional, code-specific extras
  }
}
```

**`error` is additive; `detail` is never removed.** The change is deliberately
non-breaking: the `detail` **value and type** are unchanged, so every pre-existing
client and test that reads FastAPI's `detail` keeps working — including the
coded-dict dialect (`{"code", "message", …}`) that the
selection/opportunity/crawl endpoints already returned. New code reads `error`.

### Field rules

| Field | Rule |
|---|---|
| `code` | Stable and machine-readable. Clients branch on this, never on `message`. |
| `message` | A human sentence. **Never** a raw JSON blob, stack trace, or bare token. |
| `request_id` | The correlation id; also echoed in the `X-Request-ID` response header. |
| `retryable` | Explicit per-error value when set, else classified from the status code. |
| `details` | Present only when a code defines extras (e.g. `current_selection_version`). |

## 2. Backend production

`app/core/errors.py` owns four registered handlers (wired in `app/main.py`):

| Handler | Covers | Result |
|---|---|---|
| `api_exception_handler` | `ApiException` raised by migrated routers | The raise's own code/message/details |
| `http_exception_shim_handler` | Legacy raw `HTTPException` + Starlette routing 404/405 | Status-derived default code; a coded dict keeps its code and lifts extras into `details` |
| `request_validation_error_handler` | `RequestValidationError` | 422 `validation_error` with **sanitized** field errors |
| `unhandled_exception_handler` | Any uncaught `Exception` | 500 `internal_error` — full detail to the log, **nothing internal to the client** |

### Raising an error

```python
from fastapi import status
from app.core.errors import ApiException
from app.core.config.errors import CODE_NOT_FOUND

raise ApiException(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Crawl not found")

# Coded dialect — `detail` keeps its exact legacy dict shape:
raise ApiException.coded(
    status.HTTP_409_CONFLICT,
    "stale_selection_version",
    "The selection changed since you loaded it.",
    details={"current_selection_version": 7},
)
```

Repeated 404s go through `app.core.http_errors.raise_not_found("Crawl")` so the detail
string stays consistent across routers.

### Two things that must never leak

1. **Pydantic internals.** `sanitize_validation_errors` strips `ctx` (raw constraint
   values), `input` (echoed payloads, possibly secrets), and the `errors.pydantic.dev`
   URL, keeping only `loc` / `message` / `type`. The transport prefix
   (`body`/`query`/`path`/…) is dropped from `loc`.
2. **Internals on a 500.** The unhandled handler logs the exception with the correlation
   id and returns a fixed message. No stack trace, no exception text, no SQL — and per
   invariant 6, never a credential.

## 3. Frontend consumption

`lib/api/client.ts` converts any non-2xx into an `ApiError` carrying
`status`, `code`, `retryable`, `requestId`, and the raw `body`.

`readErrorBody` extracts a display-safe message in strict priority order, so the same
UI code works against migrated and unmigrated endpoints alike:

1. canonical `error.message` / `error.code` / `error.retryable` / `error.request_id`;
2. string `detail` (classic FastAPI);
3. object `detail.message` / `detail.code` (legacy coded dialect);
4. FastAPI validation array — first item humanized as `field.path: message`;
5. the response status text.

**A raw JSON blob is never surfaced as a message** at any step.

### Transport guarantees

- **Bounded timeout** per attempt (`getApiRequestTimeoutMs`, default 30s, override with
  `NEXT_PUBLIC_API_REQUEST_TIMEOUT_MS`). An expiry becomes a retryable
  `code: 'request_timeout'` — never an endless spinner.
- **Bounded retry** (max 2 attempts, `API_RETRY_BACKOFF_MS` linear backoff) for GET and
  idempotent calls only — **never** an ordinary mutation.
- A caller's own `AbortSignal` stays a plain abort and is never retried.

### Displaying a failure

`MutationNotice` (`components/ui/mutation-notice.tsx` + `lib/api/mutation-notice.ts`) is
the shared mutation-failure surface:

- **4xx** — show the server's reason **verbatim**. It is actionable and user-caused; a
  "try again" invitation would be wrong (the same request will fail identically).
- **5xx / network** — show retry copy plus the `request_id` for support.

## 4. Response validation policy (tolerant-on-unknown)

Full rationale in [`frontend-architecture.md`](frontend-architecture.md) §6. In short:
response objects use `responseObject` (zod `.strip()`), so an **additive** backend field
can never break a screen, while a **declared** field that goes missing still fails loud.
Tolerance is prevented from becoming silent divergence by the contract-drift guard
(`lib/api/contract-drift.ts`; `pnpm check:contract`), which FAILs on missing declared
fields and WARNs on undeclared additive ones.

## 5. Adding a new error code

1. Add the constant to `backend/app/core/config/errors.py` (invariant 1 — never inline).
2. Raise it via `ApiException` / `ApiException.coded` from the owning router.
3. If the frontend must branch on it, handle the `code` in the calling module — do not
   match on `message` text.
4. Cover it in `backend/tests/component/test_error_envelope_api.py`.
# Staged Site Health and Commerce codes

The shared error envelope includes the following stable coded failures for
these routes: `url_hard_excluded`, `url_out_of_scope`,
`url_preview_invalid`, `crawl_limit_not_available`, `acquisition_budget_exceeded`,
`scraperapi_unavailable`, `opportunity_guidance_unavailable`,
`opportunity_guidance_idempotency_conflict`,
`commerce_candidate_not_found`, `commerce_candidate_already_accepted`,
`competitor_match_requires_review`, and `comparison_snapshot_unavailable`.
They use the existing `{ code, message, request_id, details? }` envelope; details
contain only safe validation or aggregate information and never secrets, raw HTML,
or provider request headers.

Workspace creation additionally uses `workspace_limit_exceeded` with a safe
`limit` detail when the account has reached the configured tenant-root cap.
