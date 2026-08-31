'use client';

import { Plus, Trash2 } from 'lucide-react';
import { useId, useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Pressable } from '@/components/ui/pressable';
import { Tooltip } from '@/components/ui/tooltip';
import type { Topic } from '@/lib/api/types';
import { cn } from '@/lib/utils';

const TOPICS_LOAD_ERROR = "Couldn't load topics. Check your connection and try again.";

/** Resolve the topic error copy: load failures outrank action failures. */
function topicErrorMessage(loadError?: boolean, actionError?: string | null): string | null {
  if (loadError) return TOPICS_LOAD_ERROR;
  return actionError ?? null;
}

/**
 * Topics selection (prompt library). Two responsive variants sharing one
 * selection model:
 *  - Desktop (lg+): a contained `bg-panel` rail listing the
 *    project's topics with per-status counts, an "All topics" bucket, an inline
 *    add-topic form, and per-topic delete.
 *  - Narrow (< lg): a compact full-width Topics picker stacked above the
 *    status tabs — the desktop rail would crush the table, so the rail
 *    collapses to a selector, preserving the IA with no overlap.
 * Selection filters the prompt table; deleting a topic detaches its prompts
 * (backend `SET NULL`) — it never deletes them. Presentational — mutations
 * live in the library container.
 */
export function TopicRail({
  topics,
  desktopId,
  selectedTopicId,
  onSelect,
  onCreate,
  onDelete,
  isCreating,
  loadError,
  actionError,
}: Readonly<{
  topics: Topic[];
  desktopId?: string;
  /** null = "All topics". */
  selectedTopicId: string | null;
  onSelect: (topicId: string | null) => void;
  /**
   * Create a topic. Returning a promise lets the rail keep the add form open
   * (with the typed name intact) when creation fails.
   */
  onCreate: (name: string) => Promise<void> | void;
  onDelete: (topic: Topic) => void;
  isCreating?: boolean;
  /** Set when the topics list failed to load. */
  loadError?: boolean;
  /** Rendered when a create/delete mutation fails. */
  actionError?: string | null;
}>) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      await onCreate(trimmed);
      // Only reset on success — a failed create keeps the form open with the
      // typed name so the user can retry without re-typing.
      setName('');
      setAdding(false);
    } catch {
      // Error surfaced via `actionError`; leave the form populated.
    }
  };

  const errorBanner = topicErrorMessage(loadError, actionError) ? (
    <Alert tone="danger" className="mx-1 mb-1">
      {topicErrorMessage(loadError, actionError)}
    </Alert>
  ) : null;

  return (
    <>
      {/* Desktop rail: raised surface that clips its own content
          so nothing from the right pane can overlap it. */}
      <nav
        id={desktopId}
        aria-label="Topics"
        className="bg-panel hidden min-w-0 content-start gap-1 rounded-lg p-1.5 lg:sticky lg:top-4 lg:grid"
      >
        <div className="flex items-center justify-between px-1">
          <h3 className={eyebrowClasses}>Topics</h3>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Add topic"
            onClick={() => setAdding((v) => !v)}
          >
            <Plus className="size-4" aria-hidden />
          </Button>
        </div>

        {errorBanner}

        {adding ? (
          <form
            className="flex items-center gap-1.5 px-1 pb-1"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <Input
              // oxlint-disable-next-line jsx-a11y/no-autofocus -- Add topic explicitly opens this form; focus follows the invoking action.
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Topic name"
              aria-label="Topic name"
              className="h-8"
            />
            <Button
              type="submit"
              variant="secondary"
              size="sm"
              disabled={isCreating || !name.trim()}
            >
              Add
            </Button>
          </form>
        ) : null}

        <TopicItem
          label="All topics"
          selected={selectedTopicId === null}
          onSelect={() => onSelect(null)}
        />
        {topics.map((topic) => (
          <TopicItem
            key={topic.id}
            label={topic.name}
            activeCount={topic.active_count}
            selected={selectedTopicId === topic.id}
            onSelect={() => onSelect(topic.id)}
            onDelete={() => onDelete(topic)}
          />
        ))}
      </nav>

      {/* Narrow selector: full-width Topics picker shown below the lg
          breakpoint, stacked above the status tabs. */}
      <TopicSelect
        topics={topics}
        selectedTopicId={selectedTopicId}
        onSelect={onSelect}
        loadError={loadError}
        actionError={actionError}
      />
    </>
  );
}

/** Compact full-width Topics selector for narrow viewports (< lg). */
function TopicSelect({
  topics,
  selectedTopicId,
  onSelect,
  loadError,
  actionError,
}: Readonly<{
  topics: Topic[];
  selectedTopicId: string | null;
  onSelect: (topicId: string | null) => void;
  loadError?: boolean;
  actionError?: string | null;
}>) {
  const labelId = useId();
  return (
    <div className="mb-1 grid gap-1.5 lg:hidden">
      <span id={labelId} className={eyebrowClasses}>
        Topics
      </span>
      <Select
        ariaLabel="Topics"
        aria-labelledby={labelId}
        value={selectedTopicId ?? ''}
        onValueChange={(value) => onSelect(value === '' ? null : value)}
        className="w-full"
        options={[
          { value: '', label: 'All topics' },
          ...topics.map((topic) => ({ value: topic.id, label: topic.name })),
        ]}
      />
      {topicErrorMessage(loadError, actionError) ? (
        <Alert tone="danger">{topicErrorMessage(loadError, actionError)}</Alert>
      ) : null}
    </div>
  );
}

function TopicItem({
  label,
  activeCount,
  selected,
  onSelect,
  onDelete,
}: Readonly<{
  label: string;
  activeCount?: number;
  selected: boolean;
  onSelect: () => void;
  onDelete?: () => void;
}>) {
  return (
    <div
      className={cn(
        'group flex min-w-0 items-center gap-0.5 rounded-sm pe-0.5',
        selected ? 'bg-accent-subtle' : 'hover:bg-background-alt',
      )}
    >
      <Pressable
        type="button"
        onClick={onSelect}
        aria-current={selected ? 'true' : undefined}
        className={cn(
          'focus-ring flex min-w-0 flex-1 items-center gap-2 rounded-sm px-2.5 py-1.5 text-left text-xs',
          selected ? 'text-accent-text font-medium' : 'text-foreground',
        )}
      >
        <Tooltip content={label}>
          <span className="min-w-0 flex-1 truncate">{label}</span>
        </Tooltip>
        {typeof activeCount === 'number' ? (
          <span className="mono text-muted shrink-0 text-xs">{activeCount}</span>
        ) : null}
      </Pressable>
      {onDelete ? (
        <Button
          type="button"
          variant="destructiveGhost"
          size="icon"
          aria-label={`Delete topic ${label}`}
          onClick={onDelete}
          className="size-8 shrink-0"
        >
          <Trash2 className="size-4" aria-hidden />
        </Button>
      ) : null}
    </div>
  );
}
