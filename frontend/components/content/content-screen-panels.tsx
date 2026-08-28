import { Check, Circle, RefreshCw, Sparkles, TrendingUp, X } from 'lucide-react';
import { type RefObject } from 'react';

import { SkillPicker } from '@/components/content/skill-picker';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import { Textarea } from '@/components/ui/input';
import { CONTENT_PROMPT_MAX_LEN } from '@/lib/api/content';
import type { ContentContextPreview } from '@/lib/api/types';
import { ICONS } from '@/lib/icons';

import {
  actionErrorMessage,
  type ContentOpportunityContext,
  type ContentSkillView,
} from './content-screen-data';

export function ContentComposer({
  prompt,
  promptRef,
  opportunity,
  demandSource,
  contextPreview,
  contextLoading,
  generating,
  skillId,
  skills,
  skillsLoading,
  canGenerate,
  onPromptChange,
  onSkillChange,
  onGenerate,
}: Readonly<{
  prompt: string;
  promptRef: RefObject<HTMLTextAreaElement | null>;
  opportunity?: ContentOpportunityContext | null;
  demandSource?: string | null;
  contextPreview?: ContentContextPreview | null;
  contextLoading?: boolean;
  generating: boolean;
  skillId: string;
  skills: readonly ContentSkillView[];
  skillsLoading: boolean;
  canGenerate: boolean;
  onPromptChange: (value: string) => void;
  onSkillChange: (value: string) => void;
  onGenerate: () => void;
}>) {
  return (
    <Card
      data-component-id="content-prompt-box"
      className="border-border bg-panel shadow-card rounded-sm border p-[var(--card-padding)]"
    >
      <CardContent className="flex flex-col gap-[var(--workspace-gap)] p-0">
        <div className="grid gap-1">
          <span className={eyebrowClasses}>New generation</span>
          <h2 className="font-display text-foreground text-xl font-semibold tracking-tight">
            What can I help you create?
          </h2>
        </div>
        {opportunity ? <OpportunityContext opportunity={opportunity} /> : null}
        {demandSource ? <DemandSource source={demandSource} /> : null}
        <Textarea
          ref={promptRef}
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value)}
          disabled={generating}
          maxLength={CONTENT_PROMPT_MAX_LEN}
          rows={demandSource || opportunity ? 10 : 4}
          aria-label="Describe the website content you want to create"
          placeholder="Describe the website content you want to create…"
          className="border-border bg-background focus:bg-panel rounded-sm p-4 text-sm leading-relaxed"
        />
        <SkillPicker
          skills={skills}
          value={skillId}
          onChange={onSkillChange}
          disabled={generating}
          loading={skillsLoading}
        />
        <div className="border-border flex flex-wrap items-end justify-between gap-4 border-t pt-4">
          <ContextIndicator preview={contextPreview} loading={contextLoading} />
          <Button
            data-component-id="content-generate-button"
            disabled={!canGenerate}
            onClick={onGenerate}
            className="gap-2 shadow-xs"
          >
            <Sparkles className="size-4" aria-hidden /> Generate
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * What CiteLadder will actually ground this draft with, before Generate.
 *
 * An unavailable source is a neutral absence, never a warning: a project
 * without Search Console is not in a degraded state, it simply has one fewer
 * optional source. Hence muted text and a hollow marker rather than a tone.
 */
function ContextIndicator({
  preview,
  loading,
}: Readonly<{ preview?: ContentContextPreview | null; loading?: boolean }>) {
  const crawlLabel = (() => {
    // Only an in-flight query shows the pending label. A settled query with
    // no preview (unreachable, errored) must still resolve to a real line —
    // otherwise the indicator sits on "Checking…" forever.
    if (loading) return 'Checking available context…';
    if (!preview?.crawl_available) return 'Website crawl · run a crawl to ground drafts';
    const pages = preview.crawl_page_count;
    return `Website crawl · ${pages} ${pages === 1 ? 'page' : 'pages'} available`;
  })();
  return (
    <div
      data-component-id="content-context-indicator"
      className="text-muted grid gap-1 text-xs font-medium"
    >
      <ContextLine available={Boolean(preview?.crawl_available)} label={crawlLabel} />
      <ContextLine
        available={Boolean(preview?.search_connected)}
        label={
          preview?.search_connected
            ? 'Search Console · connected'
            : 'Search Console · not connected'
        }
      />
    </div>
  );
}

function ContextLine({ available, label }: Readonly<{ available: boolean; label: string }>) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {available ? (
        <Check className="text-accent size-3.5 shrink-0" aria-hidden />
      ) : (
        <Circle className="size-3.5 shrink-0" aria-hidden />
      )}
      {label}
    </span>
  );
}

/**
 * The opportunity in its own words. The previous version said only that a
 * link would be kept, which told the user nothing about what they were
 * being asked to write — and the backend never sent the text to the model
 * either. Both halves are fixed together.
 */
function OpportunityContext({ opportunity }: Readonly<{ opportunity: ContentOpportunityContext }>) {
  return (
    <div
      data-component-id="content-opportunity-context"
      className="border-border bg-well grid gap-2 rounded-sm border p-4"
    >
      <span className={eyebrowClasses}>Based on opportunity</span>
      <p className="text-foreground text-sm font-semibold">{opportunity.title}</p>
      {opportunity.remediation ? (
        <p className="text-secondary text-sm leading-relaxed">{opportunity.remediation}</p>
      ) : null}
      {opportunity.target ? (
        <p className="text-muted text-xs">Target: {opportunity.target}</p>
      ) : null}
    </div>
  );
}

function DemandSource({ source }: Readonly<{ source: string }>) {
  return (
    <div
      data-component-id="content-demand-source"
      className="border-accent-border bg-accent-soft text-secondary flex items-start gap-2.5 rounded-sm border p-3.5 text-sm"
    >
      <TrendingUp className="text-accent-text mt-0.5 size-4 shrink-0" aria-hidden />
      <span>
        Brief written from the search demand signal{' '}
        <span className="text-foreground font-semibold">{source}</span>. Edit anything below before
        generating.
      </span>
    </div>
  );
}

export function GeneratingPanel({
  selectedId,
  cancelling,
  onCancel,
}: Readonly<{
  selectedId: string | null;
  cancelling: boolean;
  onCancel: (generationId: string) => void;
}>) {
  return (
    <Card
      data-component-id="content-generating-panel"
      className="border-border bg-panel shadow-card rounded-sm border p-[var(--card-padding)]"
    >
      <CardContent className="flex items-center gap-4 p-0">
        <div role="status" aria-label="Generating content" className="flex items-center gap-3">
          <ICONS.spinner className="text-accent size-5 animate-spin" aria-hidden />
          <span className="text-foreground text-sm font-medium">Generating your content…</span>
        </div>
        <div className="ml-auto">
          <Button
            variant="secondary"
            data-component-id="content-cancel-button"
            disabled={!selectedId || cancelling}
            onClick={() => selectedId && onCancel(selectedId)}
            size="sm"
          >
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function GenerationErrorPanel({
  mutationError,
  failedGenerationId,
  retrying,
  onTryAgain,
  onDismiss,
}: Readonly<{
  mutationError: unknown;
  failedGenerationId: string | null;
  retrying: boolean;
  onTryAgain: (generationId: string) => void;
  onDismiss: () => void;
}>) {
  return (
    <Card
      data-component-id="content-error-panel"
      className="border-danger-border bg-danger-bg shadow-card rounded-sm border p-[var(--card-padding)]"
    >
      <CardContent className="flex flex-col gap-4 p-0">
        <div role="alert" className="text-danger-text flex items-start gap-2.5 text-sm">
          <ICONS.warning className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span className="leading-relaxed font-medium">
            {mutationError
              ? actionErrorMessage(mutationError)
              : 'Generation failed. You can edit your prompt and try again.'}
          </span>
        </div>
        <div className="flex gap-2.5 pt-1">
          {failedGenerationId ? (
            <Button
              data-component-id="content-retry-button"
              disabled={retrying}
              onClick={() => onTryAgain(failedGenerationId)}
              size="sm"
            >
              <RefreshCw className="mr-1.5 size-3.5" aria-hidden />
              Try again
            </Button>
          ) : null}
          <Button
            variant="secondary"
            data-component-id="content-dismiss-button"
            onClick={onDismiss}
            size="sm"
          >
            <X className="mr-1.5 size-3.5" aria-hidden />
            Dismiss
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
