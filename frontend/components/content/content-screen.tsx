'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import { CONTENT_PROMPT_MAX_LEN, type SiteHealthReferenceInput } from '@/lib/api/content';
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
  useSiteHealthHandoff,
} from './content-screen-data';
import { ContentComposer, GenerationErrorPanel, GeneratingPanel } from './content-screen-panels';
import { GenerationResult } from './content-screen-result';
import { GenerationHistory } from './content-screen-history';

const FALLBACK_SKILL_ID = 'content_page';

function replaceAutomaticPrompt(
  current: string,
  next: string,
  priority: number,
  automatic: { current: { value: string; priority: number } | null },
): string {
  const previous = automatic.current;
  const userEdited = current.trim().length > 0 && current !== previous?.value;
  if (userEdited || (previous?.priority ?? 0) > priority) return current;
  automatic.current = { value: next, priority };
  return next;
}

function replaceAutomaticSkill(
  current: string | null,
  next: string,
  priority: number,
  automatic: { current: { priority: number } | null },
  userSelected: { current: boolean },
): string | null {
  if (userSelected.current || (automatic.current?.priority ?? -1) > priority) return current;
  automatic.current = { priority };
  return next;
}

/** Project-aware content entry point that resets transient state on project switch. */
export function ContentScreen({
  opportunityId,
  demandSignalId,
  siteHealthReference,
}: Readonly<{
  opportunityId?: string | null;
  demandSignalId?: string | null;
  siteHealthReference?: SiteHealthReferenceInput;
}>) {
  const activeProject = useActiveProject();
  if (!activeProject) return <NoProjectState />;

  return (
    <ProjectContentScreen
      key={activeProject.id}
      projectId={activeProject.id}
      opportunityId={opportunityId}
      demandSignalId={demandSignalId}
      siteHealthReference={
        siteHealthReference?.project_id === activeProject.id ? siteHealthReference : undefined
      }
    />
  );
}

function NoProjectState() {
  return (
    <Card>
      <CardContent className="flex flex-col items-start gap-3 py-[var(--empty-state-padding)]">
        <p className="text-secondary text-sm">
          Create a project first — content generation needs a project and its website.
        </p>
        <Link
          href="/projects"
          className="text-accent-text text-sm font-medium underline underline-offset-4"
        >
          Go to Projects
        </Link>
      </CardContent>
    </Card>
  );
}

function ProjectContentScreen({
  projectId,
  opportunityId,
  demandSignalId,
  siteHealthReference,
}: Readonly<{
  projectId: string;
  opportunityId?: string | null;
  demandSignalId?: string | null;
  siteHealthReference?: SiteHealthReferenceInput;
}>) {
  const [prompt, setPrompt] = useState('');
  const [chosenSkillId, setChosenSkillId] = useState<string | null>(null);
  const promptRef = useRef<HTMLTextAreaElement | null>(null);
  const [reasonOpen, setReasonOpen] = useState(false);
  const skillCatalog = useSkillCatalog();
  const demand = useDemandBrief(projectId, demandSignalId);
  const contextPreview = useContentContextPreview(projectId);
  const opportunity = useOpportunityContext(opportunityId);
  const siteHealth = useSiteHealthHandoff(siteHealthReference);
  const generation = useContentGenerations(
    projectId,
    undefined,
    opportunityId,
    siteHealthReference,
  );
  const detail: ContentGenerationDetail | null = generation.detailQuery.data ?? null;
  const automaticPrompt = useRef<{ value: string; priority: number } | null>(null);
  const automaticSkill = useRef<{ priority: number } | null>(null);
  const userSelectedSkill = useRef(false);
  const seededBrief = useRef<string | null>(null);

  // Seed only a newly arrived brief; subsequent snapshot refreshes must not overwrite edits.
  useEffect(() => {
    const brief = demand.brief;
    if (!brief || seededBrief.current === brief.prompt) return;
    seededBrief.current = brief.prompt;
    setPrompt((current) => replaceAutomaticPrompt(current, brief.prompt, 1, automaticPrompt));
    setChosenSkillId((current) =>
      replaceAutomaticSkill(current, brief.suggestedSkillId, 1, automaticSkill, userSelectedSkill),
    );
  }, [demand.brief]);

  // Seed once from the opportunity, on the same guarded pattern as the demand
  // brief: a later refetch must never overwrite what the user has typed.
  const seededOpportunity = useRef<string | null>(null);
  useEffect(() => {
    if (!opportunity?.taskSeed || seededOpportunity.current === opportunity.id) return;
    seededOpportunity.current = opportunity.id;
    setPrompt((current) =>
      replaceAutomaticPrompt(current, opportunity.taskSeed, 2, automaticPrompt),
    );
    setChosenSkillId((current) =>
      replaceAutomaticSkill(
        current,
        opportunity.suggestedSkillId,
        2,
        automaticSkill,
        userSelectedSkill,
      ),
    );
  }, [opportunity]);

  const seededSiteHealth = useRef<string | null>(null);
  useEffect(() => {
    const handoff = siteHealth.data;
    if (!handoff || seededSiteHealth.current === handoff.source_analysis_id) return;
    seededSiteHealth.current = handoff.source_analysis_id;
    const task = [...handoff.expected_capability, ...handoff.remediation].join('\n');
    setPrompt((current) => replaceAutomaticPrompt(current, task, 3, automaticPrompt));
    setChosenSkillId((current) =>
      replaceAutomaticSkill(
        current,
        handoff.suggested_skill_id,
        3,
        automaticSkill,
        userSelectedSkill,
      ),
    );
  }, [siteHealth.data]);

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

  return (
    <ContentWorkspace
      demand={demand}
      siteHealth={siteHealth}
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
      setChosenSkillId={(value) => {
        userSelectedSkill.current = true;
        setChosenSkillId(value);
      }}
      onGenerate={() => enqueue(generation, trimmedPrompt, skillId, canGenerate)}
      generation={generation}
      mutationError={mutationError}
      failed={failed}
      detail={detail}
      reasonOpen={reasonOpen}
      setReasonOpen={setReasonOpen}
    />
  );
}

function ContentWorkspace({
  demand,
  siteHealth,
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
  reasonOpen,
  setReasonOpen,
}: Readonly<{
  demand: ReturnType<typeof useDemandBrief>;
  siteHealth: ReturnType<typeof useSiteHealthHandoff>;
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
  reasonOpen: boolean;
  setReasonOpen: (value: boolean) => void;
}>) {
  let siteHealthAlert = null;
  if (siteHealth.isError) {
    siteHealthAlert = (
      <Alert tone="danger">
        The Site Health readiness evidence could not be authorized or loaded.
      </Alert>
    );
  } else if (siteHealth.data) {
    siteHealthAlert = (
      <Alert tone="info">
        This draft will use the persisted {siteHealth.data.dimension} readiness gap and its bounded
        crawl evidence.
      </Alert>
    );
  }
  return (
    <div className="grid grid-cols-1 items-start gap-[var(--workspace-gap)] xl:grid-cols-[minmax(0,1fr)_320px] [&>*]:min-w-0">
      <div className="flex min-w-0 flex-col gap-[var(--workspace-gap)]">
        <DemandAlerts notFound={demand.notFound} failed={demand.failed} />
        {siteHealthAlert}
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
        <GenerationStatePanels
          generating={generating}
          generation={generation}
          mutationError={mutationError}
          failed={failed}
          detail={detail}
          reasonOpen={reasonOpen}
          setReasonOpen={setReasonOpen}
        />
      </div>
      <div className="w-full min-w-0 xl:sticky xl:top-[var(--workspace-gap)]">
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

function GenerationStatePanels({
  generating,
  generation,
  mutationError,
  failed,
  detail,
  reasonOpen,
  setReasonOpen,
}: Readonly<{
  generating: boolean;
  generation: ReturnType<typeof useContentGenerations>;
  mutationError: unknown;
  failed: boolean;
  detail: ContentGenerationDetail | null;
  reasonOpen: boolean;
  setReasonOpen: (value: boolean) => void;
}>) {
  if (generating) {
    return (
      <GeneratingPanel
        selectedId={generation.selectedId}
        cancelling={generation.cancelMutation.isPending}
        onCancel={generation.cancelMutation.mutate}
      />
    );
  }
  if (mutationError || failed) {
    return (
      <GenerationErrorPanel
        mutationError={mutationError}
        failedGenerationId={failed && detail ? detail.id : null}
        retrying={generation.tryAgainMutation.isPending}
        onTryAgain={generation.tryAgainMutation.mutate}
        onDismiss={() => dismiss(generation)}
      />
    );
  }
  if (detail?.status !== 'succeeded' || !detail.output_text) return null;
  return (
    <GenerationResult
      detail={detail}
      regenerating={generation.regenerateMutation.isPending}
      feedbackPending={generation.feedbackMutation.isPending}
      onExport={() => exportMarkdown(detail)}
      onRegenerate={generation.regenerateMutation.mutate}
      reasonOpen={reasonOpen}
      onRejectClick={() => setReasonOpen(true)}
      onFeedback={(generationId, feedback, reason) => {
        setReasonOpen(false);
        generation.feedbackMutation.mutate({ generationId, feedback, reason });
      }}
    />
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

function exportMarkdown(detail: ContentGenerationDetail) {
  // A result can change while actions remain mounted; never export an empty draft.
  if (!detail.output_text) return;
  saveBlob(
    new Blob([detail.output_text], { type: 'text/markdown;charset=utf-8' }),
    `content-${detail.id.slice(0, 8)}.md`,
  );
}
