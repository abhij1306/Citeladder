/**
 * Frontend operational configuration.
 *
 * This is the single owner for tunable client limits, request bounds, polling
 * cadences, and the same-origin API base. Feature modules may re-export values
 * for backwards compatibility, but must not redefine them.
 */

// Same-origin API transport (invariant 12).
export const API_BASE_URL = '/api/v1';

/**
 * Bounded default fetch timeout (A3). Every API request attempt is wrapped in
 * `AbortSignal.timeout(...)`; an expiry surfaces as a retryable network-class
 * `ApiError` (`code: 'request_timeout'`). Env-overridable via
 * `NEXT_PUBLIC_API_REQUEST_TIMEOUT_MS` (invariant 1); read lazily so tests and
 * Next.js environments can change it without re-importing this module.
 */
export const DEFAULT_API_REQUEST_TIMEOUT_MS = 30_000;

export function getApiRequestTimeoutMs(): number {
  const raw = process.env.NEXT_PUBLIC_API_REQUEST_TIMEOUT_MS;
  const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_API_REQUEST_TIMEOUT_MS;
}

/**
 * Bounded backoff between the API client's network-failure retries (A3). The
 * delay is multiplied by the attempt number, so attempt 2 waits one unit.
 */
export const API_RETRY_BACKOFF_MS = 150;

/**
 * Contract-drift guard (A5) knobs — the dev/CI tool that diffs the backend
 * OpenAPI response models against the zod contracts. `check:contract` reads
 * the live backend only as a last resort, so its origin and timeout are
 * tunable here rather than inline in the guard (invariant 1).
 */
/**
 * Overridable via `CONTRACT_BACKEND_ORIGIN` so a non-default dev setup or a CI
 * job can point the guard at its own backend without editing code. The
 * localhost default keeps the common case zero-config. Read from `process.env`
 * directly (not `NEXT_PUBLIC_*`): this is a build-time/CLI tool that never runs
 * in the browser, so the value must not be inlined into the client bundle.
 */
export const CONTRACT_BACKEND_ORIGIN =
  process.env.CONTRACT_BACKEND_ORIGIN?.trim() || 'http://localhost:8000';
export const CONTRACT_LIVE_FETCH_TIMEOUT_MS = 2_000;
export const CONTRACT_CODEGEN_TIMEOUT_MS = 120_000;

// Evidence request/display bounds.
export const EVIDENCE_LIMIT = 100;

// Content request and list bounds.
export const CONTENT_PROMPT_MAX_LEN = 4_000;
export const CONTENT_LIST_DEFAULT_LIMIT = 50;

// Audit launch bounds.
export const MIN_REPETITIONS = 1;
export const MAX_REPETITIONS = 10;
export const DEFAULT_REPETITIONS = 1;

// Initial user-editable batch size for advanced Site Health controls. The
// backend remains authoritative for entitlement and maximum limits.
export const SITE_HEALTH_DEFAULT_PHASE_BATCH_SIZE = 10;

// Polling cadences and retry ceilings.
export const ACTIVE_RUN_POLL_MS = 3_000;
export const CONTENT_LIST_POLL_MS = 3_000;
export const CONTENT_DETAIL_POLL_MS = 2_000;
export const SYNC_RUN_POLL_MS = 3_000;
export const ATTRIBUTION_RECOMPUTE_POLL_MS = 3_000;
