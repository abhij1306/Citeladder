'use client';

import { Sparkles } from 'lucide-react';
import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input, inputClasses } from '@/components/ui/input';
import { httpErrorStatus, humanizeApiError } from '@/lib/api/errors';
import type { PromptGenerateInput } from '@/lib/api/prompts';
import type { PromptGenerateResponse, Topic } from '@/lib/api/types';

/**
 * AI generation dialog (Generate Prompts & Topics). Collects count + optional
 * target topic. Validated suggestions become active portfolio entries; this
 * bounded derivation never runs or schedules an audit.
 */
export function GeneratePromptsDialog({
  open,
  onOpenChange,
  topics,
  defaultTopicId,
  onGenerate,
  isGenerating,
  error,
  result,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  topics: Topic[];
  /** Preselect the topic the user is currently viewing (null = all). */
  defaultTopicId?: string | null;
  onGenerate: (input: PromptGenerateInput) => Promise<void> | void;
  isGenerating?: boolean;
  error?: unknown;
  /** Set after a successful run so the dialog can summarize it. */
  result?: PromptGenerateResponse | null;
}>) {
  const [count, setCount] = useState('10');
  const [topicId, setTopicId] = useState<string>(defaultTopicId ?? '');

  // Sync from the controlled `open` prop, not `handleOpenChange`: the parent
  // can open the dialog without a Dialog-driven open event, and the
  // preselected topic must still track the current view. Render-time state
  // adjustment (not an effect) per the React "you might not need an effect"
  // guidance.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) setTopicId(defaultTopicId ?? '');
  }

  const parsedCount = Number.parseInt(count, 10);
  const countValid = Number.isFinite(parsedCount) && parsedCount >= 1 && parsedCount <= 20;

  const handleOpenChange = (next: boolean) => onOpenChange(next);

  const submit = async () => {
    if (!countValid) return;
    await onGenerate({
      count: parsedCount,
      topic_id: topicId || undefined,
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={handleOpenChange}
      title="Generate prompts & topics"
      description="CiteLadder drafts topic-organized prompt suggestions from your brand profile."
      className="w-130"
      footer={
        <>
          <Button variant="ghost" onClick={() => handleOpenChange(false)}>
            {result ? 'Close' : 'Cancel'}
          </Button>
          <Button
            variant="primary"
            onClick={() => void submit()}
            disabled={isGenerating || !countValid}
          >
            <Sparkles className="size-4" aria-hidden />
            {isGenerating ? 'Generating…' : 'Generate'}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {error ? <GenerateErrorAlert error={error} /> : null}
        {result && !error ? <GenerateResultAlert result={result} /> : null}

        <label className="grid gap-1.5">
          <span className="text-secondary text-xs font-medium">Number of prompts (1–20)</span>
          <Input
            type="number"
            min={1}
            max={20}
            value={count}
            onChange={(event) => setCount(event.target.value)}
            aria-label="Number of prompts"
            aria-invalid={!countValid}
          />
        </label>

        <label className="grid gap-1.5">
          <span className="text-secondary text-xs font-medium">Topic</span>
          <select
            value={topicId}
            onChange={(event) => setTopicId(event.target.value)}
            aria-label="Topic"
            className={inputClasses}
          >
            <option value="">Let AI propose topics</option>
            {topics.map((topic) => (
              <option key={topic.id} value={topic.id}>
                {topic.name}
              </option>
            ))}
          </select>
        </label>
      </div>
    </Dialog>
  );
}

/** "1 prompt" / "3 prompts". Module scope — it closes over nothing. */
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

/**
 * Success summary for validated prompts added to the active portfolio.
 */
function GenerateResultAlert({ result }: Readonly<{ result: PromptGenerateResponse }>) {
  const total = result.generated.length;
  const active = result.generated.filter((prompt) => prompt.status === 'active').length;

  // Count topics that actually received generated rows — i.e. the unique
  // non-null topic_id values on `generated` — rather than every topic the run
  // touched (`result.topics` also includes topics whose only change was a
  // dropped duplicate, so it can overstate where rows landed).
  const topicCount = new Set(
    result.generated.map((prompt) => prompt.topic_id).filter((id): id is string => id != null),
  ).size;

  const placements: string[] = [];
  if (active > 0) placements.push(`${plural(active, 'prompt')} added to Active`);

  return (
    <Alert tone="success">
      Generated {plural(total, 'prompt')}
      {topicCount > 0 ? ` across ${plural(topicCount, 'topic')}` : ''}
      {result.dropped_duplicates > 0
        ? `; ${plural(result.dropped_duplicates, 'duplicate')} skipped`
        : ''}
      .{placements.length > 0 ? ` ${placements.join('; ')}.` : ''}
    </Alert>
  );
}

/** Map generation failures to actionable copy (503 config, 502 provider, 4xx). */
function GenerateErrorAlert({ error }: Readonly<{ error: unknown }>) {
  const status = httpErrorStatus(error);
  if (status === 429) {
    const retryAfter = humanizeApiError(error).retryAfterSeconds;
    return (
      <Alert tone="warning">
        The AI provider is rate limited. Try again
        {retryAfter ? ` in about ${retryAfter} seconds` : ' in a moment'}.
      </Alert>
    );
  }
  if (status === 503) {
    return (
      <Alert tone="warning">
        No AI provider is configured. Set <code>DEFAULT_AGENT_API_KEY</code> (and optionally{' '}
        <code>DEFAULT_AGENT_BASE_URL</code> / <code>DEFAULT_AGENT_MODEL</code>) in the backend
        environment, then try again.
      </Alert>
    );
  }
  if (status === 502) {
    return (
      <Alert tone="danger">
        The AI provider call failed or returned unusable output. Try again in a moment.
      </Alert>
    );
  }
  const message =
    error instanceof Error && error.message
      ? error.message
      : 'Generation failed. Please try again.';
  return <Alert tone="danger">{message}</Alert>;
}
