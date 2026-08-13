import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { mswServer } from '@/test/msw-server';
import { agentApi, agentTaskRunSchema } from './agent';
import { queryKeys } from './query-keys';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const RUN_ID = '22222222-2222-4222-8222-222222222222';

const run = {
  id: RUN_ID,
  project_id: PROJECT_ID,
  task_type: 'explain',
  objective: 'Explain the latest evidence.',
  task_policy_version: 'growth-agent-v2',
  status: 'completed',
  result: {
    answer: 'The latest evidence is available.',
    limitations: [],
    artifact_refs: [{ kind: 'site_snapshot', id: RUN_ID }],
  },
  provider_adapter: 'deterministic',
  endpoint_host: '',
  model: '',
  instruction_version: 'v2',
  usage: null,
  latency_ms: 10,
  error_code: '',
  error_detail: '',
  attempt_count: 1,
  completed_at: '2026-08-09T00:00:01Z',
  cancelled_at: null,
  created_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:01Z',
  attempts: [],
};

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('Growth Agent task API', () => {
  it('lists and reads only the retained task projections', async () => {
    mswServer.use(
      http.get('/api/v1/agent/tasks', () => HttpResponse.json([run])),
      http.get(`/api/v1/agent/tasks/${RUN_ID}`, () => HttpResponse.json(run)),
    );

    expect(await agentApi.listTasks(PROJECT_ID)).toEqual([run]);
    expect(await agentApi.getTask(PROJECT_ID, RUN_ID)).toEqual(run);
    expect(queryKeys.agent.tasks(PROJECT_ID)).toEqual(['agent', 'tasks', PROJECT_ID]);
    expect(queryKeys.agent.task(PROJECT_ID, RUN_ID)).toEqual(['agent', 'task', PROJECT_ID, RUN_ID]);
  });

  it('submits one fixed task and preserves its idempotency key', async () => {
    let body: unknown;
    let idempotencyKey: string | null = null;
    mswServer.use(
      http.post('/api/v1/agent/tasks', async ({ request }) => {
        body = await request.json();
        idempotencyKey = request.headers.get('idempotency-key');
        return HttpResponse.json(run, { status: 201 });
      }),
    );

    await agentApi.submitTask(
      { project_id: PROJECT_ID, task_type: 'explain', objective: 'Explain the latest evidence.' },
      'agent-idempotency-key',
    );

    expect(body).toEqual({
      project_id: PROJECT_ID,
      task_type: 'explain',
      objective: 'Explain the latest evidence.',
    });
    expect(idempotencyKey).toBe('agent-idempotency-key');
  });

  it('cancels through the retained action and strips removed contract fields', async () => {
    mswServer.use(
      http.post(`/api/v1/agent/tasks/${RUN_ID}/cancel`, () =>
        HttpResponse.json({ ...run, status: 'cancelled' }),
      ),
    );

    expect((await agentApi.cancel(PROJECT_ID, RUN_ID)).status).toBe('cancelled');
    const parsed = agentTaskRunSchema.parse({
      ...run,
      conversation_id: RUN_ID,
      industry_pack_id: 'education',
      decisions: [],
      citations: [],
    });
    expect(parsed).not.toHaveProperty('conversation_id');
    expect(parsed).not.toHaveProperty('industry_pack_id');
    expect(parsed).not.toHaveProperty('decisions');
    expect(parsed).not.toHaveProperty('citations');
  });

  it('rejects removed and unknown task types', () => {
    expect(() => agentTaskRunSchema.parse({ ...run, task_type: 'create_brief' })).toThrow();
  });
});
