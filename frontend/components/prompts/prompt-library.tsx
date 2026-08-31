'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { promptsApi, type PromptGenerateInput, type PromptInput } from '@/lib/api/prompts';
import { queryKeys } from '@/lib/api/query-keys';
import { topicsApi } from '@/lib/api/topics';
import type {
  Prompt,
  PromptGenerateResponse,
  PromptSet,
  PromptStatus,
  Topic,
} from '@/lib/api/types';
import { emptyFilters, filterPrompts, type PromptFilters } from '@/lib/prompts/filter';
import { usePromptSet } from '@/lib/prompts/use-prompt-set';
import { Tabs } from '@/components/ui/tabs';

import { PromptEmptyState } from './prompt-empty-state';
import { PromptLibraryDialogs } from './prompt-library-dialogs';
import { PromptTable } from './prompt-table';
import { PromptToolbar } from './prompt-toolbar';
import { ResizablePromptWorkspace } from './resizable-prompt-workspace';
import { TopicRail } from './topic-rail';

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return 'Something went wrong. Please try again.';
}

function mutationErrorMessage(
  create: { isError: boolean; error: unknown },
  update: { isError: boolean; error: unknown },
): string | undefined {
  if (create.isError) return errorMessage(create.error);
  return update.isError ? errorMessage(update.error) : undefined;
}

const STATUS_TABS: { id: PromptStatus; label: string }[] = [
  { id: 'active', label: 'Active' },
  { id: 'archived', label: 'Archived' },
];

/**
 * Prompt library client (F7). Owns the active prompt set (via F5 project
 * context), the topic/status/search filter state, and every CRUD, import,
 * lifecycle, and AI-generation mutation. Layout: topics rail on the left;
 * Active / Archived status tabs over the prompt table on the
 * right. The desktop split is user-resizable; "Generate prompts"
 * opens the consent-gated AI dialog.
 */
// react-doctor-disable-next-line react-doctor/no-giant-component -- this component only orchestrates queries/mutations; toolbar, topic rail, table, empty state, and dialogs are extracted.
export function PromptLibrary({ onDoneManaging }: Readonly<{ onDoneManaging?: () => void }>) {
  const queryClient = useQueryClient();
  const { projectId, promptSet, prompts, isLoading, isError, ensurePromptSet } = usePromptSet();

  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState<PromptFilters>(emptyFilters);
  const [statusTab, setStatusTab] = useState<PromptStatus>('active');
  const [selectedTopicId, setSelectedTopicId] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Prompt | undefined>(undefined);
  const [importOpen, setImportOpen] = useState(false);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [generateResult, setGenerateResult] = useState<PromptGenerateResponse | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const topicsQuery = useQuery({
    queryKey: queryKeys.topics.list(projectId ?? ''),
    queryFn: ({ signal }) => topicsApi.list(projectId as string, { signal }),
    enabled: Boolean(projectId),
  });
  const topics: Topic[] = useMemo(() => topicsQuery.data ?? [], [topicsQuery.data]);

  const invalidate = async () => {
    if (projectId) {
      await queryClient.invalidateQueries({ queryKey: queryKeys.prompts.sets(projectId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.topics.list(projectId) });
    }
    if (promptSet)
      await queryClient.invalidateQueries({ queryKey: queryKeys.prompts.set(promptSet.id) });
    // The projects list embeds prompt_sets[].prompts, which the onboarding
    // "Getting Started" card reads to mark the "Add prompts" step done. Refresh
    // it so adding prompts (via generate, manual, or import) advances the flow.
    await queryClient.invalidateQueries({ queryKey: queryKeys.projects.list() });
  };

  const createMutation = useMutation({
    mutationFn: async (input: PromptInput) => {
      const set = await ensurePromptSet();
      return promptsApi.createPrompt(set.id, input);
    },
    onSuccess: async () => {
      await invalidate();
      setFormOpen(false);
      setEditing(undefined);
    },
  });

  const updateMutation = useMutation({
    mutationFn: (vars: { id: string; input: Partial<PromptInput> }) =>
      promptsApi.updatePrompt(vars.id, vars.input),
    onSuccess: async () => {
      await invalidate();
      setFormOpen(false);
      setEditing(undefined);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => promptsApi.deletePrompt(id),
    onSettled: () => setBusyId(null),
    onSuccess: invalidate,
  });

  const toggleMutation = useMutation({
    mutationFn: (prompt: Prompt) =>
      promptsApi.updatePrompt(prompt.id, { enabled: !prompt.enabled }),
    onSettled: () => setBusyId(null),
    onSuccess: invalidate,
  });

  const statusMutation = useMutation({
    mutationFn: (vars: { prompt: Prompt; status: PromptStatus }) =>
      promptsApi.updatePrompt(vars.prompt.id, { status: vars.status }),
    onSettled: () => setBusyId(null),
    onSuccess: invalidate,
  });

  const importMutation = useMutation({
    mutationFn: async (rows: PromptInput[]): Promise<PromptSet> => {
      const set = await ensurePromptSet();
      return promptsApi.importRows(set.id, rows);
    },
    onSuccess: async () => {
      await invalidate();
      setImportOpen(false);
    },
  });

  const generateMutation = useMutation({
    mutationFn: async (input: PromptGenerateInput) => {
      const set = await ensurePromptSet();
      return promptsApi.generate(set.id, input);
    },
    // Clear any prior success summary before a new attempt so a stale result
    // can never render alongside a later retry's error.
    onMutate: () => setGenerateResult(null),
    onSuccess: async (result) => {
      setGenerateResult(result);
      if (result.generated.length > 0) setStatusTab('active');
      // Reset the topic filter to "All topics" so freshly generated rows are
      // visible even if the run landed them in a topic other than the one the
      // user was viewing.
      setSelectedTopicId(null);
      await invalidate();
    },
  });

  const createTopicMutation = useMutation({
    mutationFn: (name: string) => topicsApi.create(projectId as string, { name }),
    onSuccess: invalidate,
  });

  const deleteTopicMutation = useMutation({
    mutationFn: (topic: Topic) => topicsApi.remove(topic.id),
    onSuccess: async (_data, topic) => {
      if (selectedTopicId === topic.id) setSelectedTopicId(null);
      await invalidate();
    },
  });

  // Status tab -> topic -> search/filters, preserving order.
  const byStatus = useMemo(
    () => prompts.filter((prompt) => prompt.status === statusTab),
    [prompts, statusTab],
  );
  const byTopic = useMemo(
    () =>
      selectedTopicId === null
        ? byStatus
        : byStatus.filter((prompt) => prompt.topic_id === selectedTopicId),
    [byStatus, selectedTopicId],
  );
  const visible = useMemo(
    () => filterPrompts(byTopic, search, filters),
    [byTopic, search, filters],
  );

  const statusCounts = useMemo(() => {
    const counts: Record<PromptStatus, number> = { active: 0, archived: 0 };
    for (const prompt of prompts) counts[prompt.status] += 1;
    return counts;
  }, [prompts]);

  const hasPrompts = prompts.length > 0;

  const openAdd = () => {
    setEditing(undefined);
    setFormOpen(true);
  };
  const openEdit = (prompt: Prompt) => {
    setEditing(prompt);
    setFormOpen(true);
  };
  const submitForm = async (input: PromptInput) => {
    if (editing) await updateMutation.mutateAsync({ id: editing.id, input }).catch(() => undefined);
    else await createMutation.mutateAsync(input).catch(() => undefined);
  };

  if (!projectId) {
    return (
      <Alert tone="info">
        Select or create a project first — prompts belong to a project&apos;s prompt set.
      </Alert>
    );
  }

  if (isLoading) {
    return (
      <div className="grid gap-3">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      {isError ? (
        <Alert tone="danger">Could not load prompts. Check your connection and try again.</Alert>
      ) : null}

      <PromptToolbar
        search={search}
        onSearchChange={setSearch}
        filters={filters}
        onFiltersChange={setFilters}
        onImport={() => setImportOpen(true)}
        onAdd={openAdd}
        onGenerate={() => {
          setGenerateResult(null);
          generateMutation.reset();
          setGenerateOpen(true);
        }}
        onDoneManaging={onDoneManaging}
      />

      <ResizablePromptWorkspace
        railId="prompt-topic-rail"
        rail={
          <TopicRail
            desktopId="prompt-topic-rail"
            topics={topics}
            selectedTopicId={selectedTopicId}
            onSelect={setSelectedTopicId}
            onCreate={async (name) => {
              await createTopicMutation.mutateAsync(name);
            }}
            onDelete={(topic) => deleteTopicMutation.mutate(topic)}
            isCreating={createTopicMutation.isPending}
            loadError={topicsQuery.isError}
            actionError={
              createTopicMutation.isError
                ? errorMessage(createTopicMutation.error)
                : deleteTopicMutation.isError
                  ? errorMessage(deleteTopicMutation.error)
                  : null
            }
          />
        }
      >
        <div className="grid min-w-0 content-start gap-3">
          <Tabs
            value={statusTab}
            onValueChange={setStatusTab}
            ariaLabel="Prompt status"
            items={STATUS_TABS.map((tab) => ({
              value: tab.id,
              label: (
                <>
                  {tab.label}
                  {statusCounts[tab.id] > 0 ? (
                    <span className="mono text-muted ml-1.5 text-xs">{statusCounts[tab.id]}</span>
                  ) : null}
                </>
              ),
            }))}
          />

          {!hasPrompts ? (
            <PromptEmptyState onAdd={openAdd} onImport={() => setImportOpen(true)} />
          ) : visible.length === 0 ? (
            <p className="text-secondary px-[var(--card-padding)] py-[var(--empty-state-padding)] text-center text-sm">
              No prompts match your search or filters.
            </p>
          ) : (
            <PromptTable
              prompts={visible}
              onEdit={openEdit}
              onDelete={(prompt) => {
                setBusyId(prompt.id);
                deleteMutation.mutate(prompt.id);
              }}
              onToggleEnabled={(prompt) => {
                setBusyId(prompt.id);
                toggleMutation.mutate(prompt);
              }}
              onSetStatus={(prompt, status) => {
                setBusyId(prompt.id);
                statusMutation.mutate({ prompt, status });
              }}
              busyId={busyId}
            />
          )}
        </div>
      </ResizablePromptWorkspace>

      <PromptLibraryDialogs
        formOpen={formOpen}
        setFormOpen={setFormOpen}
        editing={editing}
        setEditing={setEditing}
        submitForm={submitForm}
        isSaving={createMutation.isPending || updateMutation.isPending}
        formError={mutationErrorMessage(createMutation, updateMutation)}
        importOpen={importOpen}
        setImportOpen={setImportOpen}
        importPrompts={async (rows) => {
          await importMutation.mutateAsync(rows).catch(() => undefined);
        }}
        isImporting={importMutation.isPending}
        importError={importMutation.isError ? errorMessage(importMutation.error) : undefined}
        generateOpen={generateOpen}
        setGenerateOpen={setGenerateOpen}
        topics={topics}
        selectedTopicId={selectedTopicId}
        generatePrompts={async (input) => {
          await generateMutation.mutateAsync(input).catch(() => undefined);
        }}
        isGenerating={generateMutation.isPending}
        generateError={generateMutation.isError ? generateMutation.error : undefined}
        generateResult={generateResult}
      />
    </div>
  );
}
