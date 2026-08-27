'use client';

import { useEffect, useRef, useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import { CONTENT_PROMPT_MAX_LEN } from '@/lib/api/content';
import type { ContentGenerationDetail } from '@/lib/api/types';
import {
  isTerminalContentStatus,
  useContentGenerations,
} from '@/lib/content/use-content-generations';
import { useActiveProject } from '@/lib/project/project-context';
import { saveBlob } from '@/lib/site-health/download';

import {
  useContentContextPreview,
  useDemandBrief,
  useOpportunityContext,
  useSkillCatalog,
} from './content-screen-data';
import { ContentComposer, GenerationErrorPanel, GeneratingPanel } from './content-screen-panels';
import { GenerationResult } from './content-screen-result';
import { GenerationHistory } from './content-screen-history';

const FALLBACK_SKILL_ID = 'content_page';

/** Project-aware content entry point that resets transient state on project switch. */
export function ContentScreen({
  opportunityId,
  demandSignalId,
}: Readonly<{ opportunityId?: string | null; demandSignalId?: string | null }>) {
  const activeProject = useActiveProject();
  if (!activeProject) return <NoProjectState />;

  return (
    <ProjectContentScreen
      key={activeProject.id}
      projectId={activeProject.id}
      opportunityId={opportunityId}
      demandSignalId={demandSignalId}
    />
  );
}

function NoProjectState() {
  return (
    <Card>
      <CardContent className="flex flex-col items-start gap-3 py-8">
        <p className="text-secondary text-sm">
          Create a project first — content generation needs a project and its website.
        </p>
        <a
          href="/projects"
          className="text-accent-text text-sm font-medium underline underline-offset-4"
        >
          Go to Projects
        </a>
      </CardContent>
    </Card>
  );
}

function ProjectContentScreen({
  projectId,
  opportunityId,
  demandSignalId,
}: Readonly<{
  projectId: string;
  opportunityId?: string | null;
  demandSignalId?: string | null;
}>) {
  const [prompt, setPrompt] = useState('');
  const [chosenSkillId, setChosenSkillId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const promptRef = useRef<HTMLTextAreaElement | null>(null);
  const [reasonOpen, setReasonOpen] = useState(false);
  const skillCatalog = useSkillCatalog();
  const demand = useDemandBrief(projectId, demandSignalId);
  const contextPreview = useContentContextPreview(projectId);
  const opportunity = useOpportunityContext(opportunityId);
  const generation = useContentGenerations(projectId, undefined, opportunityId);
  const detail: ContentGenerationDetail | null = generation.detailQuery.data ?? null;
  const seededBrief = useRef<string | null>(null);

  // Seed only a newly arrived brief; subsequent snapshot refreshes must not overwrite edits.
  useEffect(() => {
    const brief = demand.brief;
    if (!brief || seededBrief.current === brief.prompt) return;
    seededBrief.current = brief.prompt;
    setPrompt(brief.prompt);
    setChosenSkillId(brief.suggestedSkillId);
  }, [demand.brief]);

  // Seed once from the opportunity, on the same guarded pattern as the demand
  // brief: a later refetch must never overwrite what the user has typed.
  const seededOpportunity = useRef<string | null>(null);
  useEffect(() => {
    if (!opportunity?.remediation || seededOpportunity.current === opportunity.remediation) return;
    seededOpportunity.current = opportunity.remediation;
    setPrompt((current) => (current.trim() ? current : opportunity.remediation));
  }, [opportunity?.remediation]);

  const generating = Boolean(
    (detail && !isTerminalContentStatus(detail.status)) || generation.enqueueMutation.isPending,
  );
  const mutationError = firstMutationError(generation);
  const failed = detail?.status === 'failed';
  const showError = !generating && (Boolean(mutationError) || failed);

  useEffect(() => {
    if (showError) promptRef.current?.focus();
  }, [showError]);

  const skills = skillCatalog.data?.skills ?? [];
  const catalogDefault = skillCatalog.data?.default_skill_id ?? FALLBACK_SKILL_ID;
  // A removed server-side skill must fall back to the catalog default, not fail enqueue validation.
  const skillId = selectedSkillId(chosenSkillId, skills, catalogDefault);
  const trimmedPrompt = prompt.trim();
  const canGenerate =
    trimmedPrompt.length > 0 && trimmedPrompt.length <= CONTENT_PROMPT_MAX_LEN && !generating;
  const clipboard = useClipboard(detail, setCopied, setCopyFailed);

  return (
    <ContentWorkspace
      demand={demand}
      prompt={prompt}
      promptRef={promptRef}
      opportunity={opportunity}
      contextPreview={contextPreview.data ?? null}
      // Only pending BEFORE the query settles: an errored preview must fall
      // through to a real line, and isLoading stays true across retries.
      contextLoading={contextPreview.isPending && !contextPreview.isError}
      generating={generating}
      skillId={skillId}
      skills={skills}
      skillsLoading={skillCatalog.isLoading}
      canGenerate={canGenerate}
      setPrompt={setPrompt}
      setChosenSkillId={setChosenSkillId}
      onGenerate={() => enqueue(generation, trimmedPrompt, skillId, canGenerate)}
      generation={generation}
      mutationError={mutationError}
      failed={failed}
      detail={detail}
      copied={copied}
      copyFailed={copyFailed}
      clipboard={clipboard}
      reasonOpen={reasonOpen}
      setReasonOpen={setReasonOpen}
    />
  );
}

function ContentWorkspace({
  demand,
  prompt,
  promptRef,
  opportunity,
  contextPreview,
  contextLoading,
  generating,
  skillId,
  skills,
  skillsLoading,
  canGenerate,
  setPrompt,
  setChosenSkillId,
  onGenerate,
  generation,
  mutationError,
  failed,
  detail,
  copied,
  copyFailed,
  clipboard,
  reasonOpen,
  setReasonOpen,
}: Readonly<{
  demand: ReturnType<typeof useDemandBrief>;
  prompt: string;
  promptRef: React.RefObject<HTMLTextAreaElement | null>;
  opportunity: ReturnType<typeof useOpportunityContext>;
  contextPreview: Parameters<typeof ContentComposer>[0]['contextPreview'];
  contextLoading: boolean;
  generating: boolean;
  skillId: string;
  skills: Parameters<typeof ContentComposer>[0]['skills'];
  skillsLoading: boolean;
  canGenerate: boolean;
  setPrompt: (value: string) => void;
  setChosenSkillId: (value: string) => void;
  onGenerate: () => void;
  generation: ReturnType<typeof useContentGenerations>;
  mutationError: unknown;
  failed: boolean;
  detail: ContentGenerationDetail | null;
  copied: boolean;
  copyFailed: boolean;
  clipboard: () => Promise<void>;
  reasonOpen: boolean;
  setReasonOpen: (value: boolean) => void;
}>) {
  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_320px] [&>*]:min-w-0">
      <div className="flex min-w-0 flex-col gap-6">
        <DemandAlerts notFound={demand.notFound} failed={demand.failed} />
        <ContentComposer
          prompt={prompt}
          promptRef={promptRef}
          opportunity={opportunity}
          contextPreview={contextPreview}
          contextLoading={contextLoading}
          demandSource={demand.brief?.sourceLabel ?? null}
          generating={generating}
          skillId={skillId}
          skills={skills}
          skillsLoading={skillsLoading}
          canGenerate={canGenerate}
          onPromptChange={setPrompt}
          onSkillChange={setChosenSkillId}
          onGenerate={onGenerate}
        />
        {generating ? (
          <GeneratingPanel
            selectedId={generation.selectedId}
            cancelling={generation.cancelMutation.isPending}
            onCancel={generation.cancelMutation.mutate}
          />
        ) : null}
        {!generating && (Boolean(mutationError) || failed) ? (
          <GenerationErrorPanel
            mutationError={mutationError}
            failedGenerationId={failed && detail ? detail.id : null}
            retrying={generation.tryAgainMutation.isPending}
            onTryAgain={generation.tryAgainMutation.mutate}
            onDismiss={() => dismiss(generation)}
          />
        ) : null}
        {!generating && detail?.status === 'succeeded' && detail.output_text ? (
          <GenerationResult
            detail={detail}
            copied={copied}
            copyLabel={copyLabel(copied, copyFailed)}
            regenerating={generation.regenerateMutation.isPending}
            feedbackPending={generation.feedbackMutation.isPending}
            onCopy={clipboard}
            onExport={() => exportMarkdown(detail)}
            onRegenerate={generation.regenerateMutation.mutate}
            reasonOpen={reasonOpen}
            onRejectClick={() => setReasonOpen(true)}
            onFeedback={(generationId, feedback, reason) => {
              setReasonOpen(false);
              generation.feedbackMutation.mutate({ generationId, feedback, reason });
            }}
          />
        ) : null}
      </div>
      <div className="w-full min-w-0 xl:sticky xl:top-6">
        <GenerationHistory
          items={generation.listQuery.data ?? []}
          loading={generation.listQuery.isLoading}
          selectedId={generation.selectedId}
          onSelect={generation.setSelectedId}
        />
      </div>
    </div>
  );
}

function DemandAlerts({ notFound, failed }: Readonly<{ notFound: boolean; failed: boolean }>) {
  return (
    <>
      {notFound ? (
        <Alert tone="warning">
          That demand signal is no longer in the latest snapshot — it may have been recomputed away.
          Start from a current signal on Search Demand, or write your own brief below.
        </Alert>
      ) : null}
      {failed ? (
        <Alert tone="danger">
          Search demand could not be loaded, so the brief for this signal could not be built. The
          signal itself may still exist — reload to try again, or write your own brief below.
        </Alert>
      ) : null}
    </>
  );
}

function firstMutationError(generation: ReturnType<typeof useContentGenerations>) {
  return (
    generation.enqueueMutation.error ??
    generation.regenerateMutation.error ??
    generation.tryAgainMutation.error ??
    generation.feedbackMutation.error ??
    null
  );
}

function selectedSkillId(
  chosen: string | null,
  skills: readonly { id: string }[],
  fallback: string,
) {
  return chosen && (skills.length === 0 || skills.some((skill) => skill.id === chosen))
    ? chosen
    : fallback;
}

function enqueue(
  generation: ReturnType<typeof useContentGenerations>,
  prompt: string,
  skillId: string,
  canGenerate: boolean,
) {
  // The button state is advisory; retain this guard for programmatic calls.
  if (!canGenerate) return;
  generation.cancelMutation.reset();
  generation.feedbackMutation.reset();
  generation.enqueueMutation.mutate({ prompt, skillId });
}

function dismiss(generation: ReturnType<typeof useContentGenerations>) {
  generation.enqueueMutation.reset();
  generation.regenerateMutation.reset();
  generation.tryAgainMutation.reset();
  generation.cancelMutation.reset();
  generation.feedbackMutation.reset();
  generation.setSelectedId(null);
}

function useClipboard(
  detail: ContentGenerationDetail | null,
  setCopied: (value: boolean) => void,
  setCopyFailed: (value: boolean) => void,
) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  return async () => {
    if (!detail?.output_text) return;
    if (timer.current) clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(detail.output_text);
      setCopyFailed(false);
      setCopied(true);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
      setCopyFailed(true);
      timer.current = setTimeout(() => setCopyFailed(false), 2000);
    }
  };
}

function copyLabel(copied: boolean, copyFailed: boolean) {
  return copied ? 'Copied' : copyFailed ? 'Copy failed' : 'Copy';
}

function exportMarkdown(detail: ContentGenerationDetail) {
  // A result can change while actions remain mounted; never export an empty draft.
  if (!detail.output_text) return;
  saveBlob(
    new Blob([detail.output_text], { type: 'text/markdown;charset=utf-8' }),
    `content-${detail.id.slice(0, 8)}.md`,
  );
}
