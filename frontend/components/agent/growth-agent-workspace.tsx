'use client';

import { useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Clock3, FileSearch, Map, ShieldCheck, X } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import type { RunStatusValue } from '@/components/ui/badge-variants';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { inputClasses, Textarea } from '@/components/ui/input';
import {
  agentApi,
  type AgentTaskRun,
  type AgentTaskRunSummary,
  type AgentTaskType,
} from '@/lib/api/agent';
import { queryKeys } from '@/lib/api/query-keys';
import { formatUtcTimestamp } from '@/lib/format';
import { useProjectContext } from '@/lib/project/project-context';
import { cn } from '@/lib/utils';

const ACTIVE_STATUSES = new Set(['queued', 'running']);
const CANCELLABLE_STATUSES = new Set(['queued', 'running']);

const TASKS: ReadonlyArray<{
  value: AgentTaskType;
  label: string;
  description: string;
  icon: typeof FileSearch;
}> = [
  {
    value: 'explain',
    label: 'Explain my latest data',
    description: 'Summarize the latest saved Site Health, Search Demand, Opportunity, and AI Visibility data.',
    icon: FileSearch,
  },
  {
    value: 'build_roadmap',
    label: 'Prioritize next steps',
    description: 'Turn the saved Opportunity order into a concise, evidence-backed list of next steps.',
    icon: Map,
  },
];

function requestedTask(value: string | null): AgentTaskType {
  return value === 'build_roadmap' ? 'build_roadmap' : 'explain';
}

function readable(value: string): string {
  return value.replaceAll('_', ' ');
}

function taskLabel(value: AgentTaskType): string {
  return TASKS.find((task) => task.value === value)?.label ?? readable(value);
}

function sourceCoverage(coverage: AgentResult['sources'][number]['coverage']): string {
  if (!coverage) return '';
  return Object.entries(coverage).reduce<string[]>((parts, [key, value]) => {
    if (value !== null && value !== '') parts.push(`${readable(key)}: ${String(value)}`);
    return parts;
  }, []).join(' · ');
}

function formatDate(value: string): string {
  return formatUtcTimestamp(value);
}

function badgeStatus(status: string): RunStatusValue {
  if (status === 'completed' || status === 'failed' || status === 'cancelled') return status;
  if (status === 'running') return 'running';
  return 'queued';
}

function RunBadge({ status }: Readonly<{ status: string }>) {
  return (
    <Badge variant="run-status" value={badgeStatus(status)} className="capitalize">
      {readable(status)}
    </Badge>
  );
}

function TaskHistory({
  runs,
  selectedId,
  loading,
  onSelect,
}: Readonly<{
  runs: AgentTaskRunSummary[] | undefined;
  selectedId: string | null;
  loading: boolean;
  onSelect: (runId: string) => void;
}>) {
  return (
    <aside className="border-border-subtle bg-background-alt rounded-lg border p-2">
      <div className="px-2 py-2">
        <h2 className="text-foreground text-sm font-semibold">Task history</h2>
        <p className="text-muted mt-0.5 text-xs">Standalone runs for this project.</p>
      </div>
      <div className="mt-1 grid gap-1" aria-label="Task history">
        {runs?.map((run) => (
          <button
            key={run.id}
            type="button"
            onClick={() => onSelect(run.id)}
            aria-pressed={selectedId === run.id}
            className={cn(
              'focus-ring min-h-12 rounded-sm px-2 py-2 text-left',
              selectedId === run.id
                ? 'bg-accent-soft text-accent-hover'
                : 'text-secondary hover:bg-background',
            )}
          >
            <span className="block truncate text-xs font-medium">{run.objective}</span>
            <span className="text-muted text-2xs mt-1 flex items-center justify-between gap-2">
              <span>{taskLabel(run.task_type)}</span>
              <span>{formatDate(run.created_at)}</span>
            </span>
          </button>
        ))}
        {!loading && !runs?.length ? (
          <p className="text-muted px-2 py-5 text-xs leading-relaxed">
            Completed and active tasks will appear here.
          </p>
        ) : null}
      </div>
    </aside>
  );
}

type AgentResult = NonNullable<AgentTaskRun['result']>;

function DataUsed({ result }: Readonly<{ result: AgentResult }>) {
  return (
    <details className="border-border-subtle bg-background rounded-md border px-3 py-3">
      <summary className="focus-ring cursor-pointer list-none rounded-sm text-sm font-medium">
        Data used
      </summary>
      <div className="border-border-subtle mt-3 grid gap-3 border-t pt-3">
        {result.sources.map((source) => (
          <div key={source.key} className="flex flex-wrap items-start justify-between gap-2 text-xs">
            <div>
              <p className="text-foreground font-medium">{source.label}</p>
              {source.reason ? <p className="text-muted mt-0.5">{source.reason}</p> : null}
              {source.window ? (
                <p className="text-muted mt-0.5">
                  {Object.values(source.window).filter(Boolean).join(' – ')}
                </p>
              ) : null}
              {sourceCoverage(source.coverage) ? (
                <p className="text-muted mt-0.5 capitalize">{sourceCoverage(source.coverage)}</p>
              ) : null}
            </div>
            <Badge variant="neutral">
              {source.availability}
            </Badge>
          </div>
        ))}
        <p className="text-muted border-border-subtle border-t pt-2 text-xs">
          {result.artifact_refs.length
            ? `${result.artifact_refs.length} saved data ${result.artifact_refs.length === 1 ? 'artifact' : 'artifacts'} supported this result.`
            : 'No saved data artifact was available for this result.'}
        </p>
      </div>
    </details>
  );
}

function Roadmap({ items }: Readonly<{ items: AgentResult['roadmap_items'] }>) {
  if (!items.length) return null;
  return (
    <section>
      <h3 className="text-foreground text-sm font-semibold">Prioritized next steps</h3>
      <ol className="mt-2 grid gap-2">
        {items.map((item) => (
          <li key={`${item.rank}:${item.title}`} className="border-border-subtle rounded-md border p-3">
            <div className="flex items-start gap-3">
              <span className="bg-accent-soft text-accent-text grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold">
                {item.rank}
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h4 className="text-foreground text-sm font-medium">{item.title}</h4>
                  <Badge variant="neutral" className="capitalize">{readable(item.severity)}</Badge>
                </div>
                <p className="text-secondary mt-1 text-sm leading-relaxed">{item.remediation}</p>
                {item.target_url ? (
                  <p className="text-muted mt-1 truncate text-xs">Target: {item.target_url}</p>
                ) : null}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function RunDetail({
  run,
  loading,
  error,
  cancelError,
  cancelling,
  onCancel,
}: Readonly<{
  run: AgentTaskRun | undefined;
  loading: boolean;
  error: boolean;
  cancelError: string;
  cancelling: boolean;
  onCancel: (run: AgentTaskRun) => void;
}>) {
  if (error && !run) {
    return <Alert tone="danger">The task could not be loaded. Refresh and try again.</Alert>;
  }
  if (loading && !run) return <p className="text-muted text-sm">Loading task…</p>;
  if (!run) {
    return (
      <div className="grid min-h-64 place-items-center text-center">
        <div>
          <ShieldCheck aria-hidden className="text-accent-text mx-auto size-6" />
          <h2 className="text-foreground mt-3 text-lg font-semibold">Choose a bounded task</h2>
          <p className="text-muted mt-1 max-w-lg text-sm">
            Each run reads persisted project evidence once and records the exact artifacts used.
          </p>
        </div>
      </div>
    );
  }

  return (
    <article className="grid gap-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-muted text-xs">{taskLabel(run.task_type)}</p>
          <h2 className="text-foreground mt-1 text-lg font-semibold">{run.objective}</h2>
          <p className="text-muted mt-1 text-xs">Started {formatDate(run.created_at)}</p>
        </div>
        <div className="flex items-center gap-2">
          <RunBadge status={run.status} />
          {CANCELLABLE_STATUSES.has(run.status) ? (
            <Button variant="ghost" size="sm" onClick={() => onCancel(run)} disabled={cancelling}>
              <X aria-hidden className="size-4" />
              {cancelling ? 'Cancelling…' : 'Cancel'}
            </Button>
          ) : null}
        </div>
      </header>

      {run.error_detail || cancelError ? (
        <div className="grid gap-2">
          {run.error_detail ? <Alert tone="danger">{run.error_detail}</Alert> : null}
          {cancelError ? <Alert tone="danger">{cancelError}</Alert> : null}
        </div>
      ) : null}

      {run.result ? (
        <section className="border-border-subtle bg-background-alt rounded-md border p-4">
          <h3 className="text-foreground text-sm font-semibold">Summary</h3>
          <p className="text-secondary mt-2 text-sm leading-relaxed whitespace-pre-wrap">
            {run.result.summary}
          </p>
          {run.result.observations.length ? (
            <div className="mt-4">
              <h4 className="text-foreground text-xs font-semibold">What the data shows</h4>
              <ul className="text-secondary mt-2 list-disc space-y-1 pl-4 text-sm">
                {run.result.observations.map((observation) => (
                  <li key={observation}>{observation}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {run.result.limitations.length ? (
            <div className="mt-4">
              <h4 className="text-foreground text-xs font-semibold">Limitations</h4>
              <ul className="text-muted mt-1 list-disc space-y-1 pl-4 text-xs">
                {run.result.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ) : ACTIVE_STATUSES.has(run.status) ? (
        <div className="text-muted flex items-center gap-2 text-sm">
          <Clock3 aria-hidden className="size-4" />
          Reading persisted evidence and preparing the result…
        </div>
      ) : null}

      {run.result ? <Roadmap items={run.result.roadmap_items} /> : null}
      {run.result ? <DataUsed result={run.result} /> : null}
    </article>
  );
}

function TaskForm({
  taskType,
  objective,
  submitting,
  error,
  onTaskTypeChange,
  onObjectiveChange,
  onSubmit,
}: Readonly<{
  taskType: AgentTaskType;
  objective: string;
  submitting: boolean;
  error: string;
  onTaskTypeChange: (value: AgentTaskType) => void;
  onObjectiveChange: (value: string) => void;
  onSubmit: () => void;
}>) {
  const selected = TASKS.find((task) => task.value === taskType) ?? TASKS[0];
  return (
    <form
      className="border-border-subtle bg-background-alt border-t p-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="mx-auto grid max-w-3xl gap-3 sm:grid-cols-[13rem_minmax(0,1fr)]">
        <Field label="Task">
          {(props) => (
            <select
              {...props}
              className={inputClasses}
              value={taskType}
              onChange={(event) => onTaskTypeChange(requestedTask(event.target.value))}
              disabled={submitting}
            >
              {TASKS.map((task) => (
                <option key={task.value} value={task.value}>
                  {task.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Objective" required error={error || undefined} hint={selected.description}>
          {(props) => (
            <Textarea
              {...props}
              value={objective}
              onChange={(event) => onObjectiveChange(event.target.value)}
              maxLength={2000}
              rows={3}
              placeholder="What should this task explain or prioritize?"
              disabled={submitting}
            />
          )}
        </Field>
        <div className="sm:col-start-2">
          <Button type="submit" disabled={submitting || !objective.trim()}>
            {submitting ? 'Starting…' : 'Start task'}
          </Button>
        </div>
      </div>
    </form>
  );
}

export function GrowthAgentWorkspace() {
  const search = useSearchParams();
  const queryClient = useQueryClient();
  const { activeProject, isLoading: projectLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;
  const taskParam = requestedTask(search.get('task'));
  const objectiveParam = search.get('objective') ?? '';
  const [taskChoice, setTaskChoice] = useState({ searchValue: taskParam, value: taskParam });
  const taskType = taskChoice.searchValue === taskParam ? taskChoice.value : taskParam;
  const [objectiveDraft, setObjectiveDraft] = useState({
    searchValue: objectiveParam,
    value: objectiveParam,
  });
  const objective =
    objectiveDraft.searchValue === objectiveParam ? objectiveDraft.value : objectiveParam;
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [formError, setFormError] = useState('');
  const [cancelError, setCancelError] = useState('');

  const tasks = useQuery({
    queryKey: queryKeys.agent.tasks(projectId ?? ''),
    queryFn: ({ signal }) => agentApi.listTasks(projectId!, { signal }),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((run) => ACTIVE_STATUSES.has(run.status)) ? 2_000 : false,
  });
  const resolvedRunId = selectedRunId ?? tasks.data?.[0]?.id ?? null;
  const task = useQuery({
    queryKey: queryKeys.agent.task(projectId ?? '', resolvedRunId ?? ''),
    queryFn: ({ signal }) => agentApi.getTask(projectId!, resolvedRunId!, { signal }),
    enabled: Boolean(projectId && resolvedRunId),
    refetchInterval: (query) =>
      query.state.data && ACTIVE_STATUSES.has(query.state.data.status) ? 2_000 : false,
  });

  const selectedRun = task.data;

  const submit = useMutation({
    mutationFn: async () => {
      if (!projectId) throw new Error('Select a project before starting a task.');
      const nextObjective = objective.trim();
      if (!nextObjective) throw new Error('Write an objective for the task.');
      return agentApi.submitTask(
        { project_id: projectId, task_type: taskType, objective: nextObjective },
        crypto.randomUUID(),
      );
    },
    onSuccess: (run) => {
      setFormError('');
      setObjectiveDraft({ searchValue: objectiveParam, value: '' });
      setSelectedRunId(run.id);
      queryClient.setQueryData(queryKeys.agent.task(run.project_id, run.id), run);
      void queryClient.invalidateQueries({ queryKey: queryKeys.agent.tasks(run.project_id) });
    },
    onError: (error) =>
      setFormError(error instanceof Error ? error.message : 'The task could not be started.'),
  });
  const cancel = useMutation({
    mutationFn: (run: AgentTaskRun) => {
      setCancelError('');
      return agentApi.cancel(run.project_id, run.id);
    },
    onSuccess: (run) => {
      setCancelError('');
      queryClient.setQueryData(queryKeys.agent.task(run.project_id, run.id), run);
      void queryClient.invalidateQueries({ queryKey: queryKeys.agent.tasks(run.project_id) });
    },
    onError: (error) =>
      setCancelError(error instanceof Error ? error.message : 'The task could not be cancelled.'),
  });

  if (projectLoading) return <p className="text-muted text-sm">Loading project…</p>;
  if (!projectId) {
    return <p className="text-muted text-sm">Create or select a project to use Growth Agent.</p>;
  }

  return (
    <div className="grid min-h-[calc(100dvh-10rem)] gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <TaskHistory
        runs={tasks.data}
        selectedId={resolvedRunId}
        loading={tasks.isLoading}
        onSelect={setSelectedRunId}
      />

      <section className="border-border bg-panel flex min-w-0 flex-col rounded-lg border">
        <header className="border-border-subtle flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <div>
            <h1 className="font-display text-foreground text-lg font-semibold">Growth Agent</h1>
            <p className="text-muted text-xs">Understand saved data or prioritize the next actions.</p>
          </div>
          <div className="text-secondary flex items-center gap-2 text-xs">
            <ShieldCheck aria-hidden className="text-accent-text size-4" />
            Read-only project evidence
          </div>
        </header>

        <div className="min-h-80 flex-1 overflow-y-auto p-4 sm:p-6">
          {tasks.isError ? (
            <Alert tone="danger">Task history could not be loaded. Refresh and try again.</Alert>
          ) : (
            <RunDetail
              run={selectedRun}
              loading={task.isLoading}
              error={task.isError}
              cancelError={cancelError}
              cancelling={cancel.isPending}
              onCancel={(run) => cancel.mutate(run)}
            />
          )}
        </div>

        <TaskForm
          taskType={taskType}
          objective={objective}
          submitting={submit.isPending}
          error={formError}
          onTaskTypeChange={(value) => setTaskChoice({ searchValue: taskParam, value })}
          onObjectiveChange={(value) => setObjectiveDraft({ searchValue: objectiveParam, value })}
          onSubmit={() => submit.mutate()}
        />
      </section>
    </div>
  );
}
