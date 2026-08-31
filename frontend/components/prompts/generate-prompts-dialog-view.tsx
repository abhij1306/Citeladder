import { Sparkles } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { httpErrorStatus, humanizeApiError } from '@/lib/api/errors';
import type { PromptGenerateResponse, Topic } from '@/lib/api/types';

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`;

function GenerateResultAlert({ result }: Readonly<{ result: PromptGenerateResponse }>) {
  const total = result.generated.length;
  const active = result.generated.filter((prompt) => prompt.status === 'active').length;
  const topicCount = new Set(
    result.generated.map((prompt) => prompt.topic_id).filter((id): id is string => id != null),
  ).size;
  const placement = active ? ` ${plural(active, 'prompt')} added to Active.` : '';
  const duplicates = result.dropped_duplicates
    ? `; ${plural(result.dropped_duplicates, 'duplicate')} skipped`
    : '';
  // Say so when the request could not be filled, rather than letting a short
  // set read as the number that was asked for.
  const shortfall =
    result.requested_count > total
      ? ` (${total} of ${result.requested_count} requested — add topics for more)`
      : '';
  return (
    <Alert tone="success">
      Generated {plural(total, 'prompt')}
      {shortfall}
      {topicCount ? ` across ${plural(topicCount, 'topic')}` : ''}
      {duplicates}.{placement}
    </Alert>
  );
}

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
  if (status === 502)
    return (
      <Alert tone="danger">
        The AI provider call failed or returned unusable output. Try again in a moment.
      </Alert>
    );
  return (
    <Alert tone="danger">
      {error instanceof Error && error.message
        ? error.message
        : 'Generation failed. Please try again.'}
    </Alert>
  );
}

export function GeneratePromptsDialogView({
  open,
  onOpenChange,
  topics,
  count,
  topicId,
  setCount,
  setTopicId,
  countValid,
  onSubmit,
  isGenerating,
  error,
  result,
  maxCount,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  topics: Topic[];
  count: string;
  topicId: string;
  setCount: (value: string) => void;
  setTopicId: (value: string) => void;
  countValid: boolean;
  onSubmit: () => void;
  isGenerating?: boolean;
  error?: unknown;
  result?: PromptGenerateResponse | null;
  maxCount: number;
}>) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Generate prompts"
      description="CiteLadder drafts prompt suggestions and creates starting topics from confirmed offerings when needed."
      className="w-130"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {result ? 'Close' : 'Cancel'}
          </Button>
          <Button variant="primary" onClick={onSubmit} disabled={isGenerating || !countValid}>
            <Sparkles className="size-4" aria-hidden />
            {isGenerating ? 'Generating…' : 'Generate'}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {topics.length === 0 ? (
          <Alert tone="info">
            No topics exist yet. CiteLadder will create them from your confirmed offerings, then
            generate prompts.
          </Alert>
        ) : null}
        {error ? <GenerateErrorAlert error={error} /> : null}
        {result && !error ? <GenerateResultAlert result={result} /> : null}
        <div className="grid gap-1.5">
          <span className="text-secondary text-xs font-medium">
            Number of prompts (1–{maxCount})
          </span>
          <Input
            type="number"
            min={1}
            max={maxCount}
            value={count}
            onChange={(event) => setCount(event.target.value)}
            aria-label="Number of prompts"
            aria-invalid={!countValid}
          />
        </div>
        {topics.length > 0 ? (
          <div className="grid gap-1.5">
            <span className="text-secondary text-xs font-medium">Topic</span>
            <Select
              value={topicId}
              onValueChange={setTopicId}
              ariaLabel="Topic"
              options={[
                { value: '', label: 'All existing topics' },
                ...topics.map((topic) => ({ value: topic.id, label: topic.name })),
              ]}
            />
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
