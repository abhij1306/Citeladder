'use client';

import { useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Circle, Clock3, Plus, Send, ShieldCheck, X } from 'lucide-react';

import { DecisionPrompt } from '@/components/intelligence/decision-prompt';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/input';
import {
  agentApi,
  type AgentConversation,
  type AgentConversationDetail,
  type AgentTaskRun,
} from '@/lib/api/agent';
import { queryKeys } from '@/lib/api/query-keys';
import { useProjectContext } from '@/lib/project/project-context';
import { cn } from '@/lib/utils';

const ACTIVE_STATUSES = new Set(['validating', 'planning', 'running', 'awaiting_task']);
const TERMINAL_STATUSES = new Set(['completed', 'partially_completed', 'failed', 'cancelled']);

function readable(value: string) {
  return value.replaceAll('_', ' ');
}

function statusIcon(status: string) {
  if (status === 'completed') return <Check aria-hidden className="size-4" />;
  if (status === 'failed' || status === 'cancelled') return <X aria-hidden className="size-4" />;
  if (status === 'running' || status === 'awaiting_task') {
    return <Clock3 aria-hidden className="size-4" />;
  }
  return <Circle aria-hidden className="size-3" />;
}

function parseScope(value: string): Record<string, unknown> {
  if (!value.trim()) return {};
  const parsed: unknown = JSON.parse(value);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error('Scope must be a JSON object.');
  }
  return parsed as Record<string, unknown>;
}

function mostRecentConversationRun(
  runs: ReadonlyArray<AgentTaskRun> | undefined,
  conversationId: string | null,
): AgentTaskRun | null {
  if (!conversationId) return null;
  return (runs ?? [])
    .filter((run) => run.conversation_id === conversationId)
    .reduce<AgentTaskRun | null>(
      (latest, run) => (!latest || run.created_at > latest.created_at ? run : latest),
      null,
    );
}

function isAwaitingAssistantReply(
  run: AgentTaskRun | null,
  conversation: AgentConversationDetail | undefined,
): boolean {
  const selectedRunAnswered = Boolean(
    run &&
    conversation?.messages.some(
      (message) => message.role === 'assistant' && message.task_run_id === run.id,
    ),
  );
  return Boolean(run && TERMINAL_STATUSES.has(run.status) && !selectedRunAnswered);
}

function TaskProgress({ run }: Readonly<{ run: AgentTaskRun }>) {
  const status = ['validating', 'planning'].includes(run.status)
    ? 'Preparing'
    : run.status === 'awaiting_task'
      ? 'Waiting for linked work'
      : 'Working';
  return (
    <details className="border-border-subtle mt-3 border-t pt-3">
      <summary className="text-muted cursor-pointer text-xs font-medium">
        {status} · {run.steps.length} {run.steps.length === 1 ? 'step' : 'steps'}
      </summary>
      <ol className="mt-3 grid gap-2">
        {run.steps.map((step) => (
          <li key={step.id} className="flex items-start gap-2 text-xs">
            <span
              className={cn(
                'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full',
                step.status === 'completed' && 'bg-success-bg text-success-text',
                ['failed', 'cancelled'].includes(step.status) && 'bg-danger-bg text-danger-text',
                ['running', 'awaiting_task', 'awaiting_user'].includes(step.status) &&
                  'bg-info-bg text-info-text',
                step.status === 'pending' && 'bg-neutral-bg text-subtle',
              )}
            >
              {statusIcon(step.status)}
            </span>
            <span className="min-w-0">
              <span className="text-foreground block">{step.name}</span>
              <span className="text-muted block capitalize">{readable(step.status)}</span>
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}

function ConversationSidebar({
  conversations,
  tasks,
  conversationId,
  loading,
  onNew,
  onSelect,
}: Readonly<{
  conversations: AgentConversation[] | undefined;
  tasks: AgentTaskRun[] | undefined;
  conversationId: string | null;
  loading: boolean;
  onNew: () => void;
  onSelect: (conversationId: string) => void;
}>) {
  return (
    <aside className="border-border-subtle bg-background-alt rounded-lg border p-2">
      <Button variant="secondary" className="w-full justify-start" onClick={onNew}>
        <Plus aria-hidden className="size-4" />
        New conversation
      </Button>
      <div className="mt-3 grid gap-1" aria-label="Conversations">
        {conversations?.map((item) => {
          const conversationRun = mostRecentConversationRun(tasks, item.id);
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelect(item.id)}
              aria-pressed={conversationId === item.id}
              className={cn(
                'focus-ring min-h-10 rounded-sm px-2 py-1.5 text-left text-xs',
                conversationId === item.id
                  ? 'bg-accent-soft text-accent-hover'
                  : 'text-secondary hover:bg-background',
              )}
            >
              <span className="block truncate font-medium">{item.title}</span>
              <span className="text-muted mt-0.5 block capitalize">
                {conversationRun ? readable(conversationRun.status) : 'Conversation'}
              </span>
            </button>
          );
        })}
        {!loading && !conversations?.length ? (
          <p className="text-muted px-2 py-4 text-xs leading-relaxed">
            Your conversations will appear here.
          </p>
        ) : null}
      </div>
    </aside>
  );
}

function ConversationMessages({
  conversationId,
  conversation,
  loading,
  error,
}: Readonly<{
  conversationId: string | null;
  conversation: AgentConversationDetail | undefined;
  loading: boolean;
  error: boolean;
}>) {
  return (
    <>
      {error ? (
        <Alert tone="danger">The conversation could not be loaded. Refresh and try again.</Alert>
      ) : null}
      {!conversationId || (!loading && !conversation?.messages.length) ? (
        <div className="mx-auto grid max-w-xl place-items-center py-16 text-center">
          <h2 className="font-display text-foreground text-xl font-semibold">
            What should we work on next?
          </h2>
          <p className="text-muted mt-2 max-w-[58ch] text-sm leading-relaxed">
            Ask for an explanation, roadmap, draft, demand analysis, or next measurement. The agent
            uses only the current project&apos;s persisted evidence and bounded tools.
          </p>
        </div>
      ) : null}
      {conversation?.messages.length ? (
        <ol className="mx-auto grid max-w-3xl gap-5">
          {conversation.messages.map((message) => (
            <li
              key={message.id}
              className={cn('flex', message.role === 'user' ? 'justify-end' : 'justify-start')}
            >
              <div
                className={cn(
                  'max-w-[85%] rounded-lg px-3.5 py-2.5 text-sm leading-relaxed',
                  message.role === 'user'
                    ? 'bg-accent text-inverse'
                    : 'bg-background-alt text-foreground border-border-subtle border',
                )}
              >
                <p className="whitespace-pre-wrap">{message.content}</p>
                {message.citations.length ? (
                  <p className="mt-2 text-xs opacity-80">
                    Grounded in {message.citations.length}{' '}
                    {message.citations.length === 1
                      ? 'project evidence source'
                      : 'project evidence sources'}
                  </p>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      ) : null}
    </>
  );
}

function ActiveTaskPanel({
  run,
  onReviewDecision,
  onCancel,
  cancelling,
}: Readonly<{
  run: AgentTaskRun | null;
  onReviewDecision: () => void;
  onCancel: (run: AgentTaskRun) => void;
  cancelling: boolean;
}>) {
  if (!run || TERMINAL_STATUSES.has(run.status)) return null;
  const pendingDecision = run.steps.find((step) => step.status === 'awaiting_user');
  return (
    <div className="mx-auto mt-5 max-w-3xl">
      {pendingDecision ? (
        <div className="border-info bg-info-bg flex flex-wrap items-center justify-between gap-3 rounded-md border p-3">
          <div>
            <p className="text-info-text text-sm font-semibold">Your decision is required</p>
            <p className="text-info-text mt-0.5 text-xs">{pendingDecision.name}</p>
          </div>
          <Button size="sm" onClick={onReviewDecision}>
            Review decision
          </Button>
        </div>
      ) : null}
      <TaskProgress run={run} />
      <Button
        variant="ghost"
        size="sm"
        className="mt-2"
        onClick={() => onCancel(run)}
        disabled={cancelling}
      >
        {cancelling ? 'Cancelling…' : 'Cancel task'}
      </Button>
    </div>
  );
}

function AgentComposer({
  objective,
  onObjectiveChange,
  onSubmit,
  submitting,
  taskAvailable,
  missingRequiredScope,
  formError,
  capabilitiesError,
}: Readonly<{
  objective: string;
  onObjectiveChange: (value: string) => void;
  onSubmit: () => void;
  submitting: boolean;
  taskAvailable: boolean;
  missingRequiredScope: string[];
  formError: string;
  capabilitiesError: boolean;
}>) {
  return (
    <form
      className="border-border-subtle bg-background-alt border-t p-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="mx-auto grid max-w-3xl gap-2">
        <Textarea
          value={objective}
          onChange={(event) => onObjectiveChange(event.target.value)}
          maxLength={2000}
          rows={3}
          aria-label="Message Growth Agent"
          placeholder="Ask the Growth Agent about your current evidence…"
          disabled={submitting}
        />
        <div className="flex flex-wrap items-center gap-2">
          {missingRequiredScope.length ? (
            <p className="text-muted max-w-xl text-xs leading-relaxed">
              This action needs a selected source item. Start it from the related Content or Demand
              workspace so the agent receives the right context.
            </p>
          ) : null}
          <Button
            type="submit"
            className="ml-auto"
            disabled={
              submitting || !objective.trim() || !taskAvailable || missingRequiredScope.length > 0
            }
          >
            <Send aria-hidden className="size-4" />
            {submitting ? 'Sending…' : 'Send'}
          </Button>
        </div>
        {formError ? (
          <p role="alert" className="text-danger-text text-xs">
            {formError}
          </p>
        ) : null}
        {capabilitiesError ? (
          <p role="alert" className="text-danger-text text-xs">
            Agent capabilities could not be loaded. Refresh and try again.
          </p>
        ) : null}
      </div>
    </form>
  );
}

export function GrowthAgentWorkspace() {
  const search = useSearchParams();
  const queryClient = useQueryClient();
  const { activeProject, isLoading: projectLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;
  const taskType = search.get('task') ?? 'explain';
  const objectiveParam = search.get('objective') ?? '';
  const [objectiveDraft, setObjectiveDraft] = useState({
    searchValue: objectiveParam,
    value: objectiveParam,
  });
  const objective =
    objectiveDraft.searchValue === objectiveParam ? objectiveDraft.value : objectiveParam;
  const setObjective = (value: string) => {
    setObjectiveDraft({ searchValue: objectiveParam, value });
  };
  const scopeText = search.get('scope') ?? '{}';
  const [conversationChoice, setConversationChoice] = useState<string | 'new' | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [formError, setFormError] = useState('');
  const [decisionError, setDecisionError] = useState('');
  const [decisionOpen, setDecisionOpen] = useState(false);

  const capabilities = useQuery({
    queryKey: queryKeys.agent.capabilities(),
    queryFn: ({ signal }) => agentApi.capabilities({ signal }),
  });
  const conversations = useQuery({
    queryKey: queryKeys.agent.conversations(projectId ?? ''),
    queryFn: ({ signal }) => agentApi.listConversations(projectId!, { signal }),
    enabled: Boolean(projectId),
  });
  const conversationId =
    conversationChoice === 'new'
      ? null
      : (conversationChoice ?? conversations.data?.[0]?.id ?? null);
  const tasks = useQuery({
    queryKey: queryKeys.agent.tasks(projectId ?? ''),
    queryFn: ({ signal }) => agentApi.listTasks(projectId!, { signal }),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((run) => ACTIVE_STATUSES.has(run.status)) ? 2_000 : false,
  });
  const selectedRun = useMemo(() => {
    if (selectedRunId) return tasks.data?.find((run) => run.id === selectedRunId) ?? null;
    return mostRecentConversationRun(tasks.data, conversationId);
  }, [conversationId, selectedRunId, tasks.data]);
  const conversation = useQuery({
    queryKey: queryKeys.agent.conversation(projectId ?? '', conversationId ?? ''),
    queryFn: ({ signal }) => agentApi.getConversation(projectId!, conversationId!, { signal }),
    enabled: Boolean(projectId && conversationId),
    refetchInterval: (query) =>
      isAwaitingAssistantReply(selectedRun, query.state.data) ? 1_000 : false,
  });

  const resolvedTaskType = capabilities.data?.task_catalog.some(
    (item) => item.task_type === taskType,
  )
    ? taskType
    : (capabilities.data?.task_catalog[0]?.task_type ?? taskType);
  const taskPolicy = capabilities.data?.task_catalog.find(
    (item) => item.task_type === resolvedTaskType,
  );
  const taskScope = useMemo(() => {
    try {
      return parseScope(scopeText);
    } catch {
      return {};
    }
  }, [scopeText]);
  const missingRequiredScope =
    taskPolicy?.required_scope.filter((key) => !String(taskScope[key] ?? '').trim()) ?? [];
  const submit = useMutation({
    mutationFn: async () => {
      if (!projectId) throw new Error('Select a project before sending a message.');
      const message = objective.trim();
      if (!message) throw new Error('Write a message for the Growth Agent.');
      const activeConversationId =
        conversationId ?? (await agentApi.createConversation(projectId, message.slice(0, 80))).id;
      const run = await agentApi.submitTask(
        {
          project_id: projectId,
          conversation_id: activeConversationId,
          task_type: resolvedTaskType,
          objective: message,
          resource_scope: taskScope,
        },
        crypto.randomUUID(),
      );
      return { run, conversationId: activeConversationId };
    },
    onSuccess: ({ run, conversationId: nextConversationId }) => {
      setFormError('');
      setObjective('');
      setConversationChoice(nextConversationId);
      setSelectedRunId(run.id);
      void queryClient.invalidateQueries({ queryKey: queryKeys.agent.tasks(run.project_id) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.agent.conversations(run.project_id),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.agent.conversation(run.project_id, nextConversationId),
      });
    },
    onError: (error) =>
      setFormError(error instanceof Error ? error.message : 'The message could not be sent.'),
  });
  const decide = useMutation({
    mutationFn: async ({ run, confirmed }: { run: AgentTaskRun; confirmed: boolean }) => {
      const remaining = run.result?.decisions_remaining;
      const decision = String(
        (Array.isArray(remaining) ? remaining[0] : null) ??
          run.steps.find((step) => step.status === 'awaiting_user')?.tool_kind ??
          '',
      );
      return agentApi.decide(run.project_id, run.id, decision, confirmed);
    },
    onSuccess: (run) => {
      setDecisionError('');
      setDecisionOpen(false);
      void queryClient.invalidateQueries({ queryKey: queryKeys.agent.tasks(run.project_id) });
      if (run.conversation_id) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.agent.conversation(run.project_id, run.conversation_id),
        });
      }
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

  const pendingDecision = selectedRun?.steps.find((step) => step.status === 'awaiting_user');
  const decisionKind = pendingDecision?.tool_kind === 'run_audit' ? 'run-audit' : 'save-content';
  if (projectLoading) return <p className="text-muted text-sm">Loading project…</p>;
  if (!projectId) {
    return (
      <p className="text-muted text-sm">Create or select a project to use the Growth Agent.</p>
    );
  }

  return (
    <div className="grid min-h-[calc(100dvh-10rem)] gap-4 lg:grid-cols-[15rem_minmax(0,1fr)]">
      <ConversationSidebar
        conversations={conversations.data}
        tasks={tasks.data}
        conversationId={conversationId}
        loading={conversations.isLoading}
        onNew={() => {
          setConversationChoice('new');
          setSelectedRunId(null);
          setObjective('');
          setFormError('');
        }}
        onSelect={(nextConversationId) => {
          setConversationChoice(nextConversationId);
          setSelectedRunId(null);
        }}
      />

      <section className="border-border bg-panel flex min-w-0 flex-col rounded-lg border">
        <header className="border-border-subtle flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <div>
            <h1 className="font-display text-foreground text-lg font-semibold">Growth Agent</h1>
            <p className="text-muted text-xs">Ask across Site, Content, and Demand evidence.</p>
          </div>
          <div className="text-secondary flex items-center gap-2 text-xs">
            <ShieldCheck aria-hidden className="text-accent-text size-4" />
            Uses approved project evidence
          </div>
        </header>

        <div className="min-h-80 flex-1 overflow-y-auto p-4 sm:p-6">
          <ConversationMessages
            conversationId={conversationId}
            conversation={conversation.data}
            loading={conversation.isLoading}
            error={conversation.isError}
          />
          <ActiveTaskPanel
            run={selectedRun}
            onReviewDecision={() => setDecisionOpen(true)}
            onCancel={(run) => cancel.mutate(run)}
            cancelling={cancel.isPending}
          />
        </div>

        <AgentComposer
          objective={objective}
          onObjectiveChange={setObjective}
          onSubmit={() => submit.mutate()}
          submitting={submit.isPending}
          taskAvailable={Boolean(taskPolicy)}
          missingRequiredScope={missingRequiredScope}
          formError={formError}
          capabilitiesError={capabilities.isError}
        />
      </section>

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
