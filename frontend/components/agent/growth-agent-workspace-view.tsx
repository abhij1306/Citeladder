import { Clock3, FileSearch, Map, ShieldCheck, X } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import type { RunStatusValue } from '@/components/ui/badge-variants';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Textarea } from '@/components/ui/textarea';
import { Select } from '@/components/ui/select';
import { Pressable } from '@/components/ui/pressable';
import type { AgentTaskRun, AgentTaskRunSummary, AgentTaskType } from '@/lib/api/agent';
import { formatUtcTimestamp } from '@/lib/format';
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
    description:
      'Summarize the latest saved Site Health, Search Demand, Opportunity, and AI Visibility data.',
    icon: FileSearch,
  },
  {
    value: 'build_roadmap',
    label: 'Prioritize next steps',
    description:
      'Turn the saved Opportunity order into a concise, evidence-backed list of next steps.',
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
  return Object.entries(coverage)
    .reduce<string[]>((parts, [key, value]) => {
      if ((typeof value === 'string' && value !== '') || typeof value === 'number') {
        parts.push(`${readable(key)}: ${String(value)}`);
      }
      return parts;
    }, [])
    .join(' · ');
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

/**
 * The workspace only ever renders inside the right-side Agent sheet, so history
 * is a collapsed disclosure rather than a fixed sidebar: at sheet width a 16rem
 * rail either stacked above the result or squeezed it.
 */
export function TaskHistory({
  runs,
  selectedId,
  onSelect,
}: Readonly<{
  runs: AgentTaskRunSummary[] | undefined;
  selectedId: string | null;
  onSelect: (runId: string) => void;
}>) {
  // Nothing to switch between until a run exists; the newest run auto-selects.
  if (!runs?.length) return null;
  return (
    <details className="border-border-subtle rounded-md border">
      <summary className="focus-ring text-secondary cursor-pointer list-none rounded-md px-3 py-2 text-xs font-medium">
        Task history · {runs.length}
      </summary>
      <div className="border-border-subtle grid gap-1 border-t p-2" aria-label="Task history">
        {runs.map((run) => (
          <Pressable
            key={run.id}
            type="button"
            onClick={() => onSelect(run.id)}
            aria-pressed={selectedId === run.id}
            className={cn(
              'focus-ring min-h-11 rounded-sm px-2 py-2 text-left',
              selectedId === run.id
                ? 'bg-accent-soft text-accent-hover'
                : 'text-secondary hover:bg-background-alt',
            )}
          >
            <span className="block truncate text-xs font-medium">{run.objective}</span>
            <span className="text-muted mt-1 flex items-center justify-between gap-2 text-xs">
              <span>{taskLabel(run.task_type)}</span>
              <span>{formatDate(run.created_at)}</span>
            </span>
          </Pressable>
        ))}
      </div>
    </details>
  );
}

type AgentResult = NonNullable<AgentTaskRun['result']>;

function DataUsed({ result }: Readonly<{ result: AgentResult }>) {
  const artifactCount = result.artifact_refs.length;
  const artifactSummary = artifactCount
    ? `${artifactCount} saved data ${artifactCount === 1 ? 'artifact' : 'artifacts'} supported this result.`
    : 'No saved data artifact was available for this result.';

  return (
    <details className="border-border-subtle bg-background rounded-md border px-3 py-3">
      <summary className="focus-ring cursor-pointer list-none rounded-sm text-sm font-medium">
        Data used
      </summary>
      <div className="border-border-subtle mt-3 grid gap-3 border-t pt-3">
        {result.sources.map((source) => {
          const coverage = sourceCoverage(source.coverage);
          const window = source.window
            ? [source.window.start, source.window.end].filter(Boolean).join(' – ')
            : '';
          return (
            <div
              key={source.key}
              className="flex flex-wrap items-start justify-between gap-2 text-xs"
            >
              <div>
                <p className="text-foreground font-medium">{source.label}</p>
                {source.reason ? <p className="text-muted mt-0.5">{source.reason}</p> : null}
                {window ? <p className="text-muted mt-0.5">{window}</p> : null}
                {coverage ? <p className="text-muted mt-0.5 capitalize">{coverage}</p> : null}
              </div>
              <Badge variant="neutral">{source.availability}</Badge>
            </div>
          );
        })}
        <p className="text-muted border-border-subtle border-t pt-2 text-xs">{artifactSummary}</p>
      </div>
    </details>
  );
}

function Roadmap({ items }: Readonly<{ items: AgentResult['roadmap_items'] }>) {
  if (!items.length) return null;
  return (
    <section>
      <h3 className="text-foreground text-sm font-medium">Prioritized next steps</h3>
      <ol className="mt-2 grid gap-2">
        {items.map((item) => (
          <li
            key={`${item.rank}:${item.title}`}
            className="border-border-subtle rounded-md border p-3"
          >
            <div className="flex items-start gap-3">
              <span className="bg-accent-soft text-accent-text grid size-6 shrink-0 place-items-center rounded-full text-xs font-medium">
                {item.rank}
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h4 className="text-foreground text-sm font-medium">{item.title}</h4>
                  <Badge variant="neutral" className="capitalize">
                    {readable(item.severity)}
                  </Badge>
                </div>
                <p className="text-secondary mt-1 text-sm leading-relaxed">{item.remediation}</p>
                {item.target_url ? (
                  <p className="text-muted mt-1 text-xs break-all">Target: {item.target_url}</p>
                ) : null}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function RunDetail({
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
  if (error && !run)
    return <Alert tone="danger">The task could not be loaded. Refresh and try again.</Alert>;
  if (loading && !run) return <p className="text-muted text-sm">Loading task…</p>;
  if (!run) return <EmptyRunDetail />;
  return (
    <LoadedRunDetail
      run={run}
      cancelError={cancelError}
      cancelling={cancelling}
      onCancel={onCancel}
    />
  );
}

function EmptyRunDetail() {
  return (
    <div className="grid min-h-64 place-items-center text-center">
      <div>
        <ShieldCheck aria-hidden className="text-accent-text mx-auto size-6" />
        <h2 className="text-foreground mt-3 text-lg font-medium">Choose a bounded task</h2>
        <p className="text-muted mt-1 max-w-lg text-sm">
          Each run reads persisted project evidence once and records the exact artifacts used.
        </p>
      </div>
    </div>
  );
}

function LoadedRunDetail({
  run,
  cancelError,
  cancelling,
  onCancel,
}: Readonly<{
  run: AgentTaskRun;
  cancelError: string;
  cancelling: boolean;
  onCancel: (run: AgentTaskRun) => void;
}>) {
  return (
    <article className="grid min-w-0 gap-[var(--workspace-gap)]">
      <RunDetailHeader run={run} cancelling={cancelling} onCancel={onCancel} />
      {run.error_detail || cancelError ? (
        <RunErrors detail={run.error_detail} cancelError={cancelError} />
      ) : null}
      {run.result ? <ResultSummary result={run.result} /> : <RunProgress status={run.status} />}
      {run.result ? <Roadmap items={run.result.roadmap_items} /> : null}
      {run.result ? <DataUsed result={run.result} /> : null}
    </article>
  );
}

function RunDetailHeader({
  run,
  cancelling,
  onCancel,
}: Readonly<{ run: AgentTaskRun; cancelling: boolean; onCancel: (run: AgentTaskRun) => void }>) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p className="text-muted text-xs">{taskLabel(run.task_type)}</p>
        <h2 className="text-foreground mt-1 text-lg font-medium">{run.objective}</h2>
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
  );
}

function RunErrors({ detail, cancelError }: Readonly<{ detail: string; cancelError: string }>) {
  return (
    <div className="grid gap-2">
      {detail ? <Alert tone="danger">{detail}</Alert> : null}
      {cancelError ? <Alert tone="danger">{cancelError}</Alert> : null}
    </div>
  );
}

function ResultSummary({ result }: Readonly<{ result: AgentResult }>) {
  return (
    <section className="border-border-subtle bg-background-alt rounded-md border p-4 break-words">
      <h3 className="text-foreground text-sm font-medium">Summary</h3>
      <p className="text-secondary mt-2 text-sm leading-relaxed whitespace-pre-wrap">
        {result.summary}
      </p>
      {result.observations.length ? (
        <ResultList heading="What the data shows" values={result.observations} />
      ) : null}
      {result.limitations.length ? (
        <ResultList heading="Limitations" values={result.limitations} muted />
      ) : null}
    </section>
  );
}

function ResultList({
  heading,
  values,
  muted = false,
}: Readonly<{ heading: string; values: string[]; muted?: boolean }>) {
  return (
    <div className="mt-4">
      <h4 className="text-foreground text-xs font-medium">{heading}</h4>
      <ul
        className={cn(
          'mt-2 list-disc space-y-1 pl-4',
          muted ? 'text-muted text-xs' : 'text-secondary text-sm',
        )}
      >
        {values.map((value, index) => (
          <li key={`${index}:${value}`}>{value}</li>
        ))}
      </ul>
    </div>
  );
}

function RunProgress({ status }: Readonly<{ status: string }>) {
  if (!ACTIVE_STATUSES.has(status)) return null;
  return (
    <div className="text-muted flex items-center gap-2 text-sm">
      <Clock3 aria-hidden className="size-4" />
      Reading persisted evidence and preparing the result…
    </div>
  );
}

export function TaskForm({
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
    // Composer geometry: the sheet is 720px wide and shares its height with the
    // result, so the form is one objective field over a task/submit row rather
    // than a full stacked page form.
    <form
      className="border-border-subtle bg-background-alt grid min-w-0 gap-3 border-t px-[var(--card-padding)] py-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <Field label="Objective" required error={error || undefined} hint={selected.description}>
        {(props) => (
          <Textarea
            {...props}
            value={objective}
            onChange={(event) => onObjectiveChange(event.target.value)}
            maxLength={2000}
            rows={2}
            placeholder="What should this task explain or prioritize?"
            disabled={submitting}
          />
        )}
      </Field>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Task" className="min-w-0 flex-1">
          {(props) => (
            <Select
              {...props}
              ariaLabel="Task"
              value={taskType}
              onValueChange={(value) => onTaskTypeChange(requestedTask(value))}
              disabled={submitting}
              options={TASKS.map((task) => ({ value: task.value, label: task.label }))}
            />
          )}
        </Field>
        <Button type="submit" disabled={submitting || !objective.trim()}>
          {submitting ? 'Starting…' : 'Start task'}
        </Button>
      </div>
    </form>
  );
}
