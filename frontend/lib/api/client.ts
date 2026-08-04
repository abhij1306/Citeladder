/**
 * Typed HTTP transport (F2).
 *
 * Same-origin only: the browser always calls a **relative** base (`/api/v1`);
 * Next.js `rewrites()` proxies `/api/:path*` to the server-only `BACKEND_ORIGIN`
 * (invariant 12). The browser never sees a cross-origin backend URL, so there is
 * no CORS preflight and no cross-origin cookie handling.
 *
 * Guarantees:
 *   - `ApiError` on any non-2xx response, carrying status + body + request id
 *     (+ the envelope's machine `code` / `retryable` classification when the
 *     backend sends them — see `readErrorBody`).
 *   - `X-Request-ID` header on mutations (and GETs that opt in) for tracing.
 *   - `AbortSignal` forwarding.
 *   - a bounded default timeout per attempt (`getApiRequestTimeoutMs`, A3) —
 *     an expiry surfaces as a RETRYABLE network-class `ApiError`
 *     (`code: 'request_timeout'`), never an endless spinner; a caller's own
 *     abort stays a plain abort (never retried).
 *   - `credentials: 'include'` (HttpOnly JWT cookie) and `cache: 'no-store'`.
 *   - bounded network-failure retry (max 2 attempts) for GET / idempotent calls
 *     only — never for ordinary mutations.
 *   - JSON enforcement: a 2xx response that is not JSON is a contract violation.
 */
import {
  API_BASE_URL,
  API_RETRY_BACKOFF_MS,
  getApiRequestTimeoutMs,
} from '@/lib/config/operational';
import { ApiError, isAbortError, isTimeoutError } from './errors';

/** Relative API base. Same-origin; proxied to BACKEND_ORIGIN by Next rewrites. */
export { API_BASE_URL } from '@/lib/config/operational';

/**
 * Active workspace id, stamped as `X-Workspace-Id` on every request when set.
 *
 * The backend's `require_active_workspace` (B3) reads this header to scope flat
 * (non-path) routes to the selected workspace, falling back to the caller's
 * default workspace when it is absent (deps.py). The shell's project context
 * (F5) calls `setActiveWorkspaceId(project.workspace_id)` whenever the active
 * project changes, so downstream project/prompt/provider/run queries are scoped
 * to the workspace the user is looking at. Same-origin proxy means a custom
 * header never triggers a CORS preflight.
 */
let activeWorkspaceId: string | null = null;

/** Set (or clear with `null`) the workspace id sent on subsequent requests. */
export function setActiveWorkspaceId(workspaceId: string | null) {
  activeWorkspaceId = workspaceId;
}

/** Current workspace id stamped on requests, or `null` (backend default). */
export function getActiveWorkspaceId() {
  return activeWorkspaceId;
}

export type ApiRequestOptions = {
  signal?: AbortSignal;
  headers?: HeadersInit;
  requestId?: string;
  idempotencyKey?: string;
  retryNetworkFailures?: boolean;
};

type ResponseKind = 'json' | 'text' | 'blob';
type RequestMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

type InternalRequestOptions = ApiRequestOptions & {
  method: RequestMethod;
  body?: BodyInit;
};

function createRequestId() {
  return (
    globalThis.crypto?.randomUUID?.() ?? `web-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

function buildHeaders(options: InternalRequestOptions, requestId: string) {
  const headers = new Headers(options.headers);
  // Keep ordinary GETs "simple" (no custom header) to avoid a CORS preflight;
  // stamp a request id on mutations and any GET that explicitly opts in.
  if (options.method !== 'GET' || options.requestId) {
    headers.set('X-Request-ID', requestId);
  }
  if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey);
  // Scope flat routes to the active workspace when one is selected; the backend
  // falls back to the caller's default workspace when this header is absent.
  if (activeWorkspaceId && !headers.has('X-Workspace-Id')) {
    headers.set('X-Workspace-Id', activeWorkspaceId);
  }
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  return headers;
}

/**
 * Per-attempt signal: the caller's abort composed with the bounded default
 * timeout (A3). An expiry aborts with a `TimeoutError` DOMException, which the
 * request loop converts into a retryable network-class `ApiError`; the
 * caller's own abort reason passes through untouched.
 */
function attemptSignal(signal?: AbortSignal) {
  const timeout = AbortSignal.timeout(getApiRequestTimeoutMs());
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

async function fetchResponse(path: string, options: InternalRequestOptions, requestId: string) {
  return fetch(`${API_BASE_URL}${path}`, {
    method: options.method,
    body: options.body,
    signal: attemptSignal(options.signal),
    cache: 'no-store',
    credentials: 'include',
    headers: buildHeaders(options, requestId),
  });
}

function canRetryNetworkFailure(options: InternalRequestOptions) {
  return (
    Boolean(options.retryNetworkFailures) &&
    (options.method === 'GET' || Boolean(options.idempotencyKey))
  );
}

async function requestResponse(path: string, options: InternalRequestOptions) {
  const requestId = options.requestId ?? createRequestId();
  const maxAttempts = canRetryNetworkFailure(options) ? 2 : 1;
  let lastError: unknown;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const response = await fetchResponse(path, options, requestId);
      if (response.ok) return { response, requestId };
      // Reading the body can itself time out (the per-attempt signal covers the
      // whole exchange, not just the headers). Without this the expiry escaped
      // as a bare TimeoutError DOMException — bypassing the retryable
      // ApiError conversion below and surfacing as an opaque failure.
      const parsed = await readErrorBody(response).catch((error: unknown) => {
        if (isTimeoutError(error)) throw timeoutApiError(requestId);
        throw error;
      });
      throw new ApiError(
        parsed.message,
        response.status,
        parsed.raw,
        response.headers.get('x-request-id') ?? parsed.requestId ?? requestId,
        {
          code: parsed.code,
          retryable: parsed.retryable,
          retryAfterSeconds: retryAfterSeconds(response.headers.get('retry-after')),
        },
      );
    } catch (error) {
      lastError = error;
      if (
        error instanceof ApiError ||
        isAbortError(error) ||
        attempt >= maxAttempts ||
        !canRetryNetworkFailure(options)
      ) {
        // A timeout expiry is converted here (not at catch time) so a GET /
        // idempotent call with attempts left retries it like any other
        // network-class failure; the final surface is the retryable ApiError.
        throw isTimeoutError(error) ? timeoutApiError(requestId) : error;
      }
      await delay(API_RETRY_BACKOFF_MS * attempt, options.signal);
    }
  }

  throw lastError instanceof Error ? lastError : new Error('Failed to reach API.');
}

/** The A3 surface: a timeout is a transient network-class failure (retryable). */
function timeoutApiError(requestId: string) {
  return new ApiError(
    'The request timed out before the API responded. Please try again.',
    0,
    '',
    requestId,
    { code: 'request_timeout', retryable: true },
  );
}

/** Parse the delta-seconds form emitted by CiteLadder's durable usage guards. */
function retryAfterSeconds(value: string | null): number | undefined {
  if (!value?.trim()) return undefined;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds >= 0 ? Math.ceil(seconds) : undefined;
}

async function parseResponse<T>(response: Response, kind: ResponseKind): Promise<T> {
  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T;
  }
  if (kind === 'text') return response.text() as Promise<T>;
  if (kind === 'blob') return response.blob() as Promise<T>;
  const contentType = response.headers.get('content-type') ?? '';
  if (!isJsonContentType(contentType)) {
    const text = await response.text();
    if (!text.trim()) return undefined as T;
    throw new ApiError('Expected JSON response from API.', response.status, text);
  }
  return response.json() as Promise<T>;
}

async function request<T>(
  method: RequestMethod,
  path: string,
  kind: ResponseKind,
  body: unknown,
  options: ApiRequestOptions = {},
) {
  const encodedBody =
    body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body);
  const { response, requestId } = await requestResponse(path, {
    ...options,
    method,
    body: encodedBody,
  });
  // Same exposure as the error-body read: a 2xx whose BODY stalls past the
  // per-attempt timeout must surface as the retryable A3 ApiError, not as a
  // raw TimeoutError DOMException the caller cannot classify.
  return parseResponse<T>(response, kind).catch((error: unknown) => {
    if (isTimeoutError(error)) throw timeoutApiError(requestId);
    throw error;
  });
}

export const apiClient = {
  get: <T>(path: string, options?: ApiRequestOptions) =>
    request<T>('GET', path, 'json', undefined, options),
  getText: (path: string, options?: ApiRequestOptions) =>
    request<string>('GET', path, 'text', undefined, options),
  getBlob: (path: string, options?: ApiRequestOptions) =>
    request<Blob>('GET', path, 'blob', undefined, options),
  post: <T>(path: string, body: unknown, options?: ApiRequestOptions) =>
    request<T>('POST', path, 'json', body, options),
  postForm: <T>(path: string, body: FormData, options?: ApiRequestOptions) =>
    request<T>('POST', path, 'json', body, options),
  put: <T>(path: string, body: unknown, options?: ApiRequestOptions) =>
    request<T>('PUT', path, 'json', body, options),
  patch: <T>(path: string, body: unknown, options?: ApiRequestOptions) =>
    request<T>('PATCH', path, 'json', body, options),
  delete: <T>(path: string, options?: ApiRequestOptions) =>
    request<T>('DELETE', path, 'json', undefined, options),
};

/**
 * Longest plain-text body still treated as a human message. Above this it is
 * an error PAGE, not a sentence — see `readErrorBody`.
 */
const MAX_PLAIN_TEXT_MESSAGE_CHARS = 200;

/**
 * True for JSON media types, including the RFC 9457 `application/problem+json`
 * dialect. `problem+json` carries a structured body, so routing it down the
 * plain-text branch would have surfaced a raw JSON blob as the message — the
 * exact thing `readErrorBody` promises never to do.
 */
function isJsonContentType(contentType: string): boolean {
  const type = contentType.split(';')[0].trim().toLowerCase();
  return type === 'application/json' || type.endsWith('+json');
}

/** The extracted, display-safe projection of an error response body (A2). */
type ErrorPayload = {
  /** Human message — never a raw JSON blob. */
  message: string;
  /** Stable machine code from the error envelope / structured detail. */
  code?: string;
  /** Server retryability classification (canonical envelope only). */
  retryable?: boolean;
  /** Envelope-carried correlation id (backstop for the response header). */
  requestId?: string;
  /** The exact raw body text, kept on `ApiError.body` for debugging. */
  raw: string;
};

/**
 * Extract a human message (+ machine code) from an error response, in
 * priority order (A2):
 *   1. canonical envelope `error.message` / `error.code` / `error.retryable`
 *      / `error.request_id` (A1);
 *   2. string `detail` (classic FastAPI `HTTPException`);
 *   3. object `detail.message` / `detail.code` (legacy structured detail);
 *   4. FastAPI validation array — the first item's `loc` + `msg`, humanized;
 *   5. the response status text.
 * A raw JSON blob is NEVER surfaced as the message.
 */
async function readErrorBody(response: Response): Promise<ErrorPayload> {
  const fallback = response.statusText || 'Request failed';
  const contentType = response.headers.get('content-type') ?? '';
  let raw = '';
  try {
    raw = await response.text();
  } catch {
    return { message: fallback, raw };
  }
  if (!isJsonContentType(contentType)) {
    // Short plain-text bodies (e.g. a proxy's one-line error) are shown as-is.
    // A LONG body is almost never a message — it is an HTML error page or a
    // stack dump — so it falls back to the status text and stays available on
    // `ApiError.body` for debugging, rather than being pasted into the UI.
    const text = raw.trim();
    const usable = text && text.length <= MAX_PLAIN_TEXT_MESSAGE_CHARS && !text.includes('<');
    return { message: usable ? text : fallback, raw };
  }
  try {
    return { ...extractFromPayload(JSON.parse(raw), fallback), raw };
  } catch {
    // An unparseable "JSON" body must not leak a blob into the message either.
    return { message: fallback, raw };
  }
}

function extractFromPayload(payload: unknown, fallback: string): Omit<ErrorPayload, 'raw'> {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return { message: fallback };
  }
  const record = payload as Record<string, unknown>;

  // 1. Canonical envelope (A1): { detail, error: { code, message, … } }.
  const envelope = record.error;
  if (envelope && typeof envelope === 'object' && !Array.isArray(envelope)) {
    const block = envelope as Record<string, unknown>;
    const message = stringField(block.message);
    if (message) {
      return {
        message,
        code: stringField(block.code),
        retryable: typeof block.retryable === 'boolean' ? block.retryable : undefined,
        requestId: stringField(block.request_id),
      };
    }
  }

  const detail = record.detail;
  // 2. String detail.
  if (typeof detail === 'string' && detail.trim()) return { message: detail };
  // 3. Object detail: { code, message, … }.
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const block = detail as Record<string, unknown>;
    const message = stringField(block.message);
    if (message) return { message, code: stringField(block.code) };
  }
  // 4. FastAPI validation array: first item humanized as `loc: msg`.
  if (Array.isArray(detail)) {
    const message = humanizeValidationItem(detail[0]);
    if (message) return { message };
  }
  // 5. Status text — the payload is never stringified into the message.
  return { message: fallback };
}

/** A non-empty trimmed string field, or undefined. */
function stringField(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

/**
 * Humanize one FastAPI validation error item (`{ loc, msg, … }`) as
 * `field.path: message`. The leading `body` loc segment is dropped (it names
 * the transport slot, not a user field); `query`/`path` are kept.
 */
function humanizeValidationItem(item: unknown): string | undefined {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return undefined;
  const record = item as Record<string, unknown>;
  const msg = stringField(record.msg);
  if (!msg) return undefined;
  const segments = Array.isArray(record.loc)
    ? record.loc.filter((part): part is string | number =>
        Boolean(
          (typeof part === 'string' && part) || (typeof part === 'number' && Number.isFinite(part)),
        ),
      )
    : [];
  if (segments[0] === 'body') segments.shift();
  const loc = segments.map(String).join('.');
  return loc ? `${loc}: ${msg}` : msg;
}

function delay(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

export { ApiError, httpErrorStatus } from './errors';
