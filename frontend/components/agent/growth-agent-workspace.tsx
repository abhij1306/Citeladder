'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, ChevronRight, Circle, Clock3, ShieldCheck, X } from 'lucide-react';

import { DecisionPrompt } from '@/components/intelligence/decision-prompt';
import { Button } from '@/components/ui/button';
import { agentApi, type AgentTaskRun } from '@/lib/api/agent';
import { queryKeys } from '@/lib/api/query-keys';
import { useProjectContext } from '@/lib/project/project-context';
import { cn } from '@/lib/utils';

const ACTIVE_STATUSES = new Set(['validating', 'planning', 'running', 'awaiting_task']);
const TERMINAL_STATUSES = new Set(['completed', 'partially_completed', 'failed', 'cancelled']);

function statusIcon(status: string) {
  if (status === 'completed') return <Check aria-hidden className="size-4" />;
  if (status === 'failed' || status === 'cancelled') return <X aria-hidden className="size-4" />;
  if (status === 'running' || status === 'awaiting_task')
    return <Clock3 aria-hidden className="size-4" />;
  return <Circle aria-hidden className="size-3" />;
}

function readable(value: string) {
  return value.replaceAll('_', ' ');
}

function unknownText(value: unknown, fallback = '') {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
}

function providerSummary(configured: boolean | undefined, adapter?: string, model?: string) {
  if (configured) return `${adapter ?? ''} · ${model ?? ''}`;
  return 'Deterministic mode · model narration unavailable';
}

function artifactHref(kind: string, id: string) {
  if (kind === 'opportunity') return `/opportunities?selected=${encodeURIComponent(id)}`;
  if (kind === 'prompt') return '/prompts';
  if (kind === 'audit_schedule') return '/runs';
  if (kind.startsWith('content_')) return '/content';
  if (kind === 'demand_snapshot') return '/demand';
  if (kind === 'site_snapshot') return '/site';
  return null;
}

function timestamp(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function parseScope(value: string): Record<string, unknown> {
  if (!value.trim()) return {};
  const parsed: unknown = JSON.parse(value);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error('Scope must be a JSON object.');
  }
  return parsed as Record<string, unknown>;
}

function ResultPanel({ run }: Readonly<{ run: AgentTaskRun }>) {
  const result = run.result;
  const limitations = Array.isArray(result?.limitations) ? result.limitations : [];
  const artifacts = Array.isArray(result?.artifacts_created) ? result.artifacts_created : [];
  const citations = Array.isArray(result?.citations) ? result.citations : [];
  const nextStep = typeof result?.next_step === 'string' ? result.next_step : '';
  const roadmap = result?.roadmap;
  const groups =
    roadmap && typeof roadmap === 'object' && !Array.isArray(roadmap)
      ? (roadmap as Record<string, unknown>).groups
      : null;

  return (
    <section
      aria-labelledby="agent-result-heading"
      className="border-border bg-panel rounded-lg border"
    >
      <div className="border-border-subtle border-b px-4 py-3">
        <h2 id="agent-result-heading" className="text-foreground text-sm font-semibold">
          Result
        </h2>
      </div>
      <div className="grid gap-5 p-4 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="min-w-0">
          <p className="text-foreground max-w-[70ch] text-sm leading-relaxed">
            {String(result?.conclusion ?? 'This run has not produced a conclusion yet.')}
          </p>
          {Array.isArray(groups) && groups.length > 0 ? (
            <ol className="border-border-subtle mt-5 divide-y border-y">
              {groups.map((group, index) => {
                const item = group as Record<string, unknown>;
                const groupItems = Array.isArray(item.items) ? item.items : [];
                return (
                  <li key={`${String(item.name)}-${index}`} className="py-4">
                    <div className="flex items-baseline justify-between gap-4">
                      <h3 className="text-foreground text-sm font-semibold capitalize">
                        {readable(unknownText(item.name, 'Other'))}
                      </h3>
                      <span className="text-subtle text-xs tabular-nums">
                        {groupItems.length} {groupItems.length === 1 ? 'action' : 'actions'}
                      </span>
                    </div>
                    <p className="text-muted mt-1 text-xs leading-relaxed">
                      {unknownText(item.rationale)}
                    </p>
                    <ul className="mt-3 grid gap-2">
                      {groupItems.map((entry, entryIndex) => {
                        const action = entry as Record<string, unknown>;
                        return (
                          <li
                            key={unknownText(action.id, String(entryIndex))}
                            className="flex gap-3 text-sm"
                          >
                            <span className="text-subtle tabular-nums">
                              {unknownText(action.rank, String(entryIndex + 1))}
                            </span>
                            <span className="text-foreground">
                              {unknownText(action.title, 'Action')}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  </li>
                );
              })}
            </ol>
          ) : null}
          {nextStep ? (
            <div className="border-border-subtle mt-5 border-t pt-4">
              <p className="text-subtle text-2xs font-medium tracking-wide uppercase">Next step</p>
              <p className="text-foreground mt-1 text-sm leading-relaxed">{nextStep}</p>
            </div>
          ) : null}
        </div>
        <aside className="border-border-subtle border-t pt-4 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-5">
          <p className="text-subtle text-2xs font-medium tracking-wide uppercase">Trust record</p>
          <dl className="mt-3 grid gap-3 text-xs">
            <div>
              <dt className="text-muted">Validation</dt>
              <dd className="text-foreground mt-0.5 font-medium capitalize">
                {String(run.validation?.status ?? 'pending')}
              </dd>
            </div>
            <div>
              <dt className="text-muted">Artifacts</dt>
              <dd className="text-foreground mt-0.5 tabular-nums">{artifacts.length}</dd>
            </div>
            <div>
              <dt className="text-muted">Model</dt>
              <dd className="text-foreground mt-0.5 break-words">{run.model}</dd>
            </div>
            <div>
              <dt className="text-muted">Usage</dt>
              <dd className="text-foreground mt-0.5 tabular-nums">
                {run.usage ? `${String(run.usage.total_tokens ?? 0)} tokens` : 'No model usage'}
              </dd>
            </div>
          </dl>
          {limitations.length > 0 ? (
            <div className="mt-5">
              <p className="text-subtle text-2xs font-medium tracking-wide uppercase">
                Limitations
              </p>
              <ul className="text-muted mt-2 grid gap-1.5 text-xs leading-relaxed">
                {limitations.map((item, index) => (
                  <li key={`${String(item)}-${index}`}>{String(item)}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {artifacts.length > 0 ? (
            <div className="mt-5">
              <p className="text-subtle text-2xs font-medium tracking-wide uppercase">Artifacts</p>
              <ul className="mt-2 grid gap-1.5 text-xs">
                {artifacts.map((value, index) => {
                  const artifact = value as Record<string, unknown>;
                  const kind = unknownText(artifact.kind, 'artifact');
                  const id = unknownText(artifact.id);
                  const href = artifactHref(kind, id);
                  return (
                    <li key={`${kind}-${id}-${index}`} className="min-w-0">
                      {href ? (
                        <Link className="text-accent-text hover:underline" href={href}>
                          {readable(kind)} · {id.slice(0, 8)}
                        </Link>
                      ) : (
                        <span className="text-muted break-all">
                          {readable(kind)} · {id}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
          {citations.length > 0 ? (
            <details className="mt-5">
              <summary className="text-subtle text-2xs cursor-pointer font-medium tracking-wide uppercase">
                Citation IDs · {citations.length}
              </summary>
              <ul className="text-muted mt-2 grid gap-1 text-xs break-all">
                {citations.map((citation) => (
                  <li key={String(citation)}>{String(citation)}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </aside>
      </div>
    </section>
  );
}

function RunTimeline({ run }: Readonly<{ run: AgentTaskRun }>) {
  return (
    <section
      aria-labelledby="agent-plan-heading"
      className="border-border bg-panel rounded-lg border p-4"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="agent-plan-heading" className="text-foreground text-sm font-semibold">
          Plan and progress
        </h2>
        <span className="text-muted text-xs capitalize">{readable(run.status)}</span>
      </div>
      <ol className="mt-4 grid gap-1">
        {run.steps.map((step) => (
          <li key={step.id} className="flex min-h-11 items-center gap-3 py-1.5">
            <span
              className={cn(
                'flex size-7 shrink-0 items-center justify-center rounded-full',
                step.status === 'completed' && 'bg-success-bg text-success-text',
                ['failed', 'cancelled'].includes(step.status) && 'bg-danger-bg text-danger-text',
                ['running', 'awaiting_task', 'awaiting_user'].includes(step.status) &&
                  'bg-info-bg text-info-text',
                step.status === 'pending' && 'bg-neutral-bg text-subtle',
              )}
            >
              {statusIcon(step.status)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-foreground text-sm">{step.name}</p>
              <p className="text-muted text-xs">
                {readable(step.tool_name)} · {readable(step.status)}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function GrowthAgentWorkspace() {
  // NOSONAR -- composition remains explicit for screen-level state
  const search = useSearchParams();
  const queryClient = useQueryClient();
  const { activeProject, isLoading: projectLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;
  const [taskType, setTaskType] = useState(search.get('task') ?? 'build_roadmap');
  const [objective, setObjective] = useState(
    search.get('objective') ?? 'Build a roadmap from the current verified evidence.',
  );
  const [scopeText, setScopeText] = useState(search.get('scope') ?? '{}');
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [formError, setFormError] = useState('');
  const [decisionError, setDecisionError] = useState('');
  const [decisionOpen, setDecisionOpen] = useState(false);

  const capabilities = useQuery({
    queryKey: queryKeys.agent.capabilities(),
    queryFn: ({ signal }) => agentApi.capabilities({ signal }),
  });
  const tasks = useQuery({
    queryKey: queryKeys.agent.tasks(projectId ?? ''),
    queryFn: ({ signal }) => agentApi.listTasks(projectId!, { signal }),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((run) => ACTIVE_STATUSES.has(run.status)) ? 2_000 : false,
  });
  const resolvedTaskType = capabilities.data?.task_catalog.some(
    (item) => item.task_type === taskType,
  )
    ? taskType
    : (capabilities.data?.task_catalog[0]?.task_type ?? taskType);
  const selectedRun = useMemo(
    () =>
      selectedRunId === null
        ? (tasks.data?.[0] ?? null)
        : (tasks.data?.find((run) => run.id === selectedRunId) ?? null),
    [selectedRunId, tasks.data],
  );

  const submit = useMutation({
    mutationFn: async () => {
      if (!projectId) throw new Error('Select a project before starting a task.');
      return agentApi.submitTask(
        {
          project_id: projectId,
          task_type: resolvedTaskType,
          objective,
          resource_scope: parseScope(scopeText),
        },
        crypto.randomUUID(),
      );
    },
    onSuccess: (run) => {
      setFormError('');
      setSelectedRunId(run.id);
      void queryClient.invalidateQueries({ queryKey: queryKeys.agent.tasks(run.project_id) });
    },
    onError: (error) =>
      setFormError(error instanceof Error ? error.message : 'The task could not start.'),
  });
  const decide = useMutation({
    mutationFn: async ({ run, confirmed }: { run: AgentTaskRun; confirmed: boolean }) => {
      const remaining = run.result?.decisions_remaining;
      const decision = String(
        (Array.isArray(remaining) ? remaining[0] : null) ??
          run.steps.find((s) => s.status === 'awaiting_user')?.tool_kind ??
          '',
      );
      return agentApi.decide(run.project_id, run.id, decision, confirmed);
    },
    onSuccess: (run) => {
      setDecisionError('');
      setDecisionOpen(false);
      void queryClient.invalidateQueries({ queryKey: queryKeys.agent.tasks(run.project_id) });
    },
    onError: (error) =>
      setDecisionError(
        error instanceof Error ? error.message : 'The decision could not be recorded. Try again.',
      ),
  });
  const cancel = useMutation({
    mutationFn: (run: AgentTaskRun) => agentApi.cancel(run.project_id, run.id),
    onSuccess: (run) => {
      setFormError('');
      void queryClient.invalidateQueries({ queryKey: queryKeys.agent.tasks(run.project_id) });
    },
    onError: (error) =>
      setFormError(error instanceof Error ? error.message : 'The task could not be cancelled.'),
  });

  const taskPolicy = capabilities.data?.task_catalog.find(
    (item) => item.task_type === resolvedTaskType,
  );
  const pendingDecision = selectedRun?.steps.find((step) => step.status === 'awaiting_user');
  const decisionKind = pendingDecision?.tool_kind === 'run_audit' ? 'run-audit' : 'save-content';
  const selectedManifest = selectedRun?.context?.manifest.selected;
  const selectedCount: number =
    selectedManifest && typeof selectedManifest === 'object'
      ? Object.values(selectedManifest as Record<string, unknown>).reduce<number>(
          (total, value) => total + (Array.isArray(value) ? value.length : 0),
          0,
        )
      : 0;
  let providerStatus = providerSummary(
    capabilities.data?.configured,
    capabilities.data?.provider_adapter,
    capabilities.data?.model,
  );
  if (capabilities.isError) providerStatus = 'Provider status unavailable';

  if (projectLoading) return <p className="text-muted text-sm">Loading project…</p>;
  if (!projectId)
    return (
      <p className="text-muted text-sm">Create or select a project to use the Growth Agent.</p>
    );

  return (
    <div className="grid gap-6">
      <header className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <h1 className="font-display text-foreground text-2xl font-semibold tracking-tight">
            Turn evidence into the next move
          </h1>
          <p className="text-muted mt-2 max-w-[70ch] text-sm leading-relaxed">
            The agent coordinates Site, Content, and Demand through bounded tasks. It cannot
            publish, change deterministic scores, or turn generated prose into project facts.
          </p>
        </div>
        <div className="border-border bg-panel flex items-center gap-3 rounded-md border px-3 py-2 text-xs">
          <ShieldCheck aria-hidden className="text-accent-text size-4" />
          <span className="text-secondary">{providerStatus}</span>
        </div>
      </header>

      <section
        className="border-border bg-panel rounded-lg border p-4"
        aria-labelledby="agent-compose-heading"
      >
        <div className="grid gap-4 lg:grid-cols-[15rem_minmax(0,1fr)_auto] lg:items-end">
          <label className="text-secondary grid gap-1.5 text-xs font-medium">
            <span id="agent-compose-heading">Supported task</span>
            <select
              value={resolvedTaskType}
              onChange={(event) => setTaskType(event.target.value)}
              className="border-border bg-panel text-foreground focus:border-accent focus:ring-accent/20 h-11 rounded-sm border px-3 text-sm outline-none focus:ring-2"
            >
              {(capabilities.data?.task_catalog ?? []).map((item) => (
                <option key={item.task_type} value={item.task_type}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          <label className="text-secondary grid gap-1.5 text-xs font-medium">
            <span>Objective</span>
            <input
              value={objective}
              onChange={(event) => setObjective(event.target.value)}
              maxLength={2000}
              className="border-border bg-panel text-foreground focus:border-accent focus:ring-accent/20 h-11 rounded-sm border px-3 text-sm outline-none focus:ring-2"
            />
          </label>
          <Button
            className="min-h-11"
            onClick={() => submit.mutate()}
            disabled={submit.isPending || !objective.trim() || !taskPolicy}
          >
            {submit.isPending ? 'Starting…' : 'Start task'}
          </Button>
        </div>
        {taskPolicy ? (
          <p className="text-muted mt-3 text-xs leading-relaxed">{taskPolicy.description}</p>
        ) : null}
        {taskPolicy?.required_scope.length ? (
          <label className="text-secondary mt-4 grid gap-1.5 text-xs font-medium">
            Resource scope · required: {taskPolicy.required_scope.join(', ')}
            <textarea
              value={scopeText}
              onChange={(event) => setScopeText(event.target.value)}
              rows={3}
              spellCheck={false}
              className="border-border bg-well text-foreground focus:border-accent focus:ring-accent/20 rounded-sm border px-3 py-2 font-sans text-xs outline-none focus:ring-2"
            />
            <span className="text-muted text-2xs">
              JSON object, for example {`{"${taskPolicy.required_scope[0]}": "…"}`}.
            </span>
          </label>
        ) : null}
        {capabilities.isError ? (
          <div className="border-danger bg-danger-bg mt-3 flex items-center justify-between gap-3 rounded-sm border p-3">
            <p role="alert" className="text-danger-text text-xs">
              Agent capabilities could not be loaded.
            </p>
            <Button variant="ghost" size="sm" onClick={() => void capabilities.refetch()}>
              Retry
            </Button>
          </div>
        ) : null}
        {formError ? (
          <p role="alert" className="text-danger-text mt-3 text-xs">
            {formError} Check the task scope and try again.
          </p>
        ) : null}
      </section>

      <div className="grid min-w-0 gap-6 xl:grid-cols-[15rem_minmax(0,1fr)]">
        <aside aria-label="Task history" className="min-w-0">
          <div className="flex items-center justify-between">
            <h2 className="text-foreground text-sm font-semibold">Task history</h2>
            <span className="text-subtle text-xs tabular-nums">{tasks.data?.length ?? 0}</span>
          </div>
          <div className="mt-3 grid gap-1">
            {tasks.data?.map((run) => (
              <button
                key={run.id}
                type="button"
                onClick={() => setSelectedRunId(run.id)}
                aria-pressed={selectedRun?.id === run.id}
                className={cn(
                  'focus:ring-accent flex min-h-11 w-full items-center gap-2 rounded-sm px-2 text-left text-xs outline-none focus:ring-2',
                  selectedRun?.id === run.id
                    ? 'bg-accent-subtle text-accent-text'
                    : 'text-secondary hover:bg-well',
                )}
              >
                <span className="shrink-0">{statusIcon(run.status)}</span>
                <span className="min-w-0 flex-1">
                  <span className="text-foreground block truncate">{run.objective}</span>
                  <span className="text-muted mt-0.5 block truncate">
                    {readable(run.task_type)} · {readable(run.status)} · {timestamp(run.updated_at)}
                  </span>
                </span>
                <ChevronRight aria-hidden className="size-3.5 shrink-0" />
              </button>
            ))}
            {tasks.isError ? (
              <div className="border-danger bg-danger-bg mt-2 rounded-sm border p-3">
                <p role="alert" className="text-danger-text text-xs">
                  Task history could not be loaded.
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-2"
                  onClick={() => void tasks.refetch()}
                >
                  Retry
                </Button>
              </div>
            ) : null}
            {!tasks.isLoading && !tasks.isError && !tasks.data?.length ? (
              <p className="text-muted py-6 text-xs leading-relaxed">
                No runs yet. Start with a roadmap or evidence explanation.
              </p>
            ) : null}
          </div>
        </aside>

        <div className="grid min-w-0 gap-4">
          {selectedRun ? (
            <>
              <RunTimeline run={selectedRun} />
              {pendingDecision ? (
                <section className="border-info bg-info-bg flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-info-text text-sm font-semibold">
                      Your decision is required
                    </p>
                    <p className="text-info-text mt-1 text-xs">{pendingDecision.name}</p>
                  </div>
                  <Button onClick={() => setDecisionOpen(true)}>Review decision</Button>
                </section>
              ) : null}
              {selectedRun.result ? <ResultPanel run={selectedRun} /> : null}
              <details className="border-border bg-panel rounded-lg border p-4">
                <summary className="text-foreground cursor-pointer text-sm font-semibold">
                  Context and evidence
                </summary>
                <div className="mt-4 grid gap-4 sm:grid-cols-3">
                  <div>
                    <p className="text-muted text-xs">Included artifacts</p>
                    <p className="text-foreground mt-1 text-sm tabular-nums">{selectedCount}</p>
                  </div>
                  <div>
                    <p className="text-muted text-xs">Omissions</p>
                    <p className="text-foreground mt-1 text-sm tabular-nums">
                      {selectedRun.context?.omissions.length ?? 0}
                    </p>
                  </div>
                  <div>
                    <p className="text-muted text-xs">Frozen context</p>
                    <p className="text-foreground mt-1 text-sm tabular-nums">
                      {selectedRun.context?.char_count ?? 0} characters
                    </p>
                  </div>
                </div>
                {selectedRun.context?.omissions.length ? (
                  <ul className="border-border-subtle text-muted mt-4 grid gap-1 border-t pt-3 text-xs">
                    {selectedRun.context.omissions.map((value, index) => {
                      const item = value as Record<string, unknown>;
                      return (
                        <li key={`${String(item.section)}-${index}`}>
                          {readable(unknownText(item.section, 'context'))}:{' '}
                          {readable(unknownText(item.reason, 'omitted'))}
                          {typeof item.count === 'number' ? ` · ${item.count}` : ''}
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
                <p className="text-muted mt-4 text-xs break-all">
                  Manifest {selectedRun.context?.manifest_hash ?? 'not available'}
                </p>
              </details>
              {!TERMINAL_STATUSES.has(selectedRun.status) ? (
                <Button
                  variant="ghost"
                  className="justify-self-start"
                  onClick={() => cancel.mutate(selectedRun)}
                  disabled={cancel.isPending}
                >
                  {cancel.isPending ? 'Cancelling…' : 'Cancel task'}
                </Button>
              ) : null}
            </>
          ) : (
            <div className="border-border bg-panel rounded-lg border p-8">
              <p className="text-foreground text-sm font-medium">Choose a bounded task</p>
              <p className="text-muted mt-2 max-w-[65ch] text-sm leading-relaxed">
                Roadmaps preserve deterministic priority. Explanations cite only frozen, authorized
                context.
              </p>
              <Link
                href="/site"
                className="text-accent-text mt-4 inline-flex text-sm font-medium hover:underline"
              >
                Review Site evidence first
              </Link>
            </div>
          )}
        </div>
      </div>

      {selectedRun && pendingDecision ? (
        <DecisionPrompt
          kind={decisionKind}
          open={decisionOpen}
          onOpenChange={setDecisionOpen}
          onConfirm={() => decide.mutate({ run: selectedRun, confirmed: true })}
          onDecline={() => decide.mutate({ run: selectedRun, confirmed: false })}
          pending={decide.isPending}
          error={decisionError}
          consequence={
            decisionKind === 'run-audit'
              ? 'Creates the configured recurring audit schedule. Each run can call paid answer engines.'
              : 'Queues one brief-driven draft as a durable Content artifact. It does not publish the draft.'
          }
        />
      ) : null}
    </div>
  );
}
