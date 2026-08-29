import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function errorJson(body: unknown, status: number, statusText = 'Error') {
  return new Response(JSON.stringify(body), {
    status,
    statusText,
    headers: { 'content-type': 'application/json' },
  });
}

describe('apiClient', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('calls a relative same-origin /api/v1 base URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await apiClient.get('/ping');

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe('/api/v1/ping');
  });

  it('throws ApiError with status and request id on 4xx', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('Bad Request', {
        status: 400,
        headers: { 'x-request-id': 'req-abc' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient, ApiError } = await import('./client');
    await expect(apiClient.get('/thing')).rejects.toMatchObject({
      name: 'ApiError',
      status: 400,
      requestId: 'req-abc',
    });
    // 4xx is not retried.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(ApiError).toBeDefined();
  });

  it('captures a numeric Retry-After hint on a rate-limited response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Workspace usage limit exceeded' }), {
        status: 429,
        headers: {
          'content-type': 'application/json',
          'retry-after': '321.2',
          'x-request-id': 'req-rate-limit',
        },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.post('/brand-discoveries', {})).rejects.toMatchObject({
      status: 429,
      retryAfterSeconds: 322,
      requestId: 'req-rate-limit',
    });
  });

  it('throws ApiError on 5xx', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('Boom', { status: 503 }));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.get('/thing')).rejects.toMatchObject({ status: 503 });
  });

  it('retries idempotent GET network failures then succeeds', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.get('/ping', { retryNetworkFailures: true })).resolves.toEqual({
      ok: true,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not retry ordinary GET network failures', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('offline'));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.get('/ping')).rejects.toThrow('offline');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not retry mutation network failures', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('offline'));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.post('/audits', { project_id: 'x' })).rejects.toThrow('offline');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('forwards AbortSignal and explicit request id', async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await apiClient.get('/ping', { signal: controller.signal, requestId: 'req-test' });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    // The caller's signal is composed with the bounded default timeout (A3) —
    // aborting the controller must still abort the request signal.
    expect(init.signal).toBeInstanceOf(AbortSignal);
    controller.abort();
    expect(init.signal?.aborted).toBe(true);
    expect(init.credentials).toBe('include');
    expect(init.cache).toBe('no-store');
    expect(new Headers(init.headers).get('X-Request-ID')).toBe('req-test');
  });

  it('uses a bounded per-request timeout override when supplied', async () => {
    const timeoutSpy = vi.spyOn(AbortSignal, 'timeout');
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await apiClient.post('/generate', {}, { timeoutMs: 195_000 });

    expect(timeoutSpy).toHaveBeenCalledWith(195_000);
  });

  it('rejects when an aborted signal fires during a retry backoff', async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockImplementation(() => {
      controller.abort();
      return Promise.reject(new Error('offline'));
    });
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(
      apiClient.get('/ping', { retryNetworkFailures: true, signal: controller.signal }),
    ).rejects.toBeTruthy();
  });

  it('keeps ordinary GET requests header-free to avoid a CORS preflight', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await apiClient.get('/ping');

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get('X-Request-ID')).toBeNull();
  });

  it('stamps a generated request id on mutations', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await apiClient.post('/audits', { project_id: 'x' });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get('X-Request-ID')).toBeTruthy();
  });

  it('throws ApiError when a 2xx response is not JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('<html>ok</html>', {
        status: 200,
        headers: { 'content-type': 'text/html' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.get('/thing')).rejects.toThrow('Expected JSON response from API.');
  });

  it('httpErrorStatus reads status from ApiError and duck-typed errors', async () => {
    const { ApiError, httpErrorStatus } = await import('./client');
    expect(httpErrorStatus(new ApiError('x', 403, '{}'))).toBe(403);
    expect(httpErrorStatus({ status: 401 })).toBe(401);
    expect(httpErrorStatus(new Error('no'))).toBeUndefined();
  });

  it('stamps X-Workspace-Id when an active workspace is set, and omits it otherwise', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({})));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient, setActiveWorkspaceId, getActiveWorkspaceId } = await import('./client');

    // No active workspace → header absent (backend uses default workspace).
    await apiClient.get('/projects');
    expect(
      new Headers((fetchMock.mock.calls[0]?.[1] as RequestInit).headers).get('X-Workspace-Id'),
    ).toBeNull();

    // Selecting a workspace stamps it on subsequent requests.
    setActiveWorkspaceId('ws-123');
    expect(getActiveWorkspaceId()).toBe('ws-123');
    await apiClient.get('/projects');
    expect(
      new Headers((fetchMock.mock.calls[1]?.[1] as RequestInit).headers).get('X-Workspace-Id'),
    ).toBe('ws-123');

    // Clearing it removes the header again.
    setActiveWorkspaceId(null);
    await apiClient.get('/projects');
    expect(
      new Headers((fetchMock.mock.calls[2]?.[1] as RequestInit).headers).get('X-Workspace-Id'),
    ).toBeNull();
  });
});

describe('readErrorBody extraction (A2)', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('prefers the canonical envelope error.message / code / retryable / request_id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      errorJson(
        {
          detail: 'fallback human string',
          error: {
            code: 'precondition_failed',
            message: 'no completed sync window is available',
            request_id: 'srv-req-1',
            retryable: false,
          },
        },
        422,
        'Unprocessable Entity',
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.post('/x', {})).rejects.toMatchObject({
      message: 'no completed sync window is available',
      status: 422,
      code: 'precondition_failed',
      retryable: false,
      // No x-request-id header → the envelope's request_id backstops it.
      requestId: 'srv-req-1',
    });
  });

  it('extracts a plain string detail (classic FastAPI HTTPException)', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(errorJson({ detail: 'Not found' }, 404, 'Not Found'));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.get('/missing')).rejects.toMatchObject({
      message: 'Not found',
      status: 404,
    });
  });

  it('extracts an object detail message + code, keeping the raw JSON body', async () => {
    const payload = {
      detail: { code: 'site_health_quota_exceeded', message: 'limit reached', limit: 50 },
    };
    const fetchMock = vi.fn().mockResolvedValue(errorJson(payload, 403, 'Forbidden'));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient, ApiError } = await import('./client');
    const error = await apiClient.get('/quota').catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as InstanceType<typeof ApiError>).message).toBe('limit reached');
    expect((error as InstanceType<typeof ApiError>).code).toBe('site_health_quota_exceeded');
    // The raw body stays parseable for structured-detail consumers.
    expect(JSON.parse((error as InstanceType<typeof ApiError>).body).detail.limit).toBe(50);
  });

  it('humanizes the first FastAPI validation item (loc + msg, body prefix dropped)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      errorJson(
        {
          detail: [
            {
              loc: ['body', 'products', 0, 'sku'],
              msg: 'field required',
              type: 'missing',
            },
          ],
        },
        422,
        'Unprocessable Entity',
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.post('/import', {})).rejects.toMatchObject({
      message: 'products.0.sku: field required',
      status: 422,
    });
  });

  it('never surfaces a raw JSON blob for an unrecognized payload shape', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(errorJson({ unexpected: 'shape' }, 400, 'Bad Request'));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.get('/odd')).rejects.toMatchObject({ message: 'Bad Request' });
  });

  it('never surfaces a raw JSON blob when the JSON body is unparseable', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{"detail": truncated', {
        status: 500,
        statusText: 'Internal Server Error',
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.get('/broken')).rejects.toMatchObject({
      message: 'Internal Server Error',
    });
  });

  it('passes a plain-text error body through (Starlette plain-text 500)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('Internal Server Error', {
        status: 500,
        headers: { 'content-type': 'text/plain' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.get('/boom')).rejects.toMatchObject({
      message: 'Internal Server Error',
      status: 500,
    });
  });
});

describe('request timeout (A3)', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('surfaces a hung request as a retryable network-class ApiError', async () => {
    // A fetch that never settles; the client's AbortSignal.timeout ends it.
    vi.stubEnv('NEXT_PUBLIC_API_REQUEST_TIMEOUT_MS', '20');
    const fetchMock = vi.fn().mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          // Bind the signal once: inside the listener TS cannot re-narrow
          // `init.signal`, so reading `.reason` off it there fails the build.
          const signal = init.signal;
          signal?.addEventListener('abort', () => reject(signal.reason));
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.get('/hang')).rejects.toMatchObject({
      name: 'ApiError',
      status: 0,
      code: 'request_timeout',
      retryable: true,
    });
    // No in-transport retry without the opt-in.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('retries a timeout in-transport for an idempotent GET, then surfaces it', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_REQUEST_TIMEOUT_MS', '20');
    const fetchMock = vi.fn().mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          // Bind the signal once: inside the listener TS cannot re-narrow
          // `init.signal`, so reading `.reason` off it there fails the build.
          const signal = init.signal;
          signal?.addEventListener('abort', () => reject(signal.reason));
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.get('/hang', { retryNetworkFailures: true })).rejects.toMatchObject({
      code: 'request_timeout',
      retryable: true,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('never converts a caller abort into a timeout error', async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          const signal = init.signal;
          signal?.addEventListener('abort', () => reject(signal.reason));
          controller.abort();
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.get('/x', { signal: controller.signal })).rejects.toMatchObject({
      name: 'AbortError',
    });
  });
});
