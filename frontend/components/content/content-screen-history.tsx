import { FileText } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import type { RunStatusValue } from '@/components/ui/badge-variants';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import { Skeleton } from '@/components/ui/skeleton';
import type { ContentGenerationListItem, ContentGenerationStatus } from '@/lib/api/types';
import { cn } from '@/lib/utils';

const STATUS_BADGE: Record<ContentGenerationStatus, RunStatusValue> = {
  queued: 'queued',
  leased: 'queued',
  running: 'running',
  retry_wait: 'running',
  succeeded: 'completed',
  failed: 'failed',
  cancelled: 'cancelled',
};

export function GenerationHistory({
  items,
  loading,
  selectedId,
  onSelect,
}: Readonly<{
  items: ContentGenerationListItem[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (generationId: string) => void;
}>) {
  return (
    <section
      data-component-id="content-history"
      className="bg-panel shadow-card border-border flex flex-col gap-3.5 rounded-sm border p-5 sm:p-6"
    >
      <div className="border-border grid gap-1 border-b pb-3">
        <span className={eyebrowClasses}>History</span>
        <h2 className="font-display text-foreground text-lg leading-tight font-semibold tracking-tight">
          Recent generations
        </h2>
      </div>
      {loading ? (
        <Skeleton className="h-24 w-full rounded-sm" />
      ) : (
        <HistoryItems items={items} selectedId={selectedId} onSelect={onSelect} />
      )}
    </section>
  );
}

function HistoryItems({
  items,
  selectedId,
  onSelect,
}: Readonly<{
  items: ContentGenerationListItem[];
  selectedId: string | null;
  onSelect: (generationId: string) => void;
}>) {
  // A sidebar rail, so the full <EmptyState> card would out-weigh the panel
  // it sits in; this keeps the same icon → line shape at rail scale.
  if (items.length === 0)
    return (
      <div className="text-muted grid justify-items-center gap-2 py-6 text-center">
        <FileText className="size-5" aria-hidden />
        <p className="text-sm">No generations yet.</p>
        <p className="text-xs">Your drafts will collect here.</p>
      </div>
    );
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <li key={item.id}>
          <button
            type="button"
            onClick={() => onSelect(item.id)}
            className={cn(
              'focus-ring hover:bg-background-alt flex w-full items-center gap-3 rounded-sm border px-3.5 py-3 text-left text-sm transition-colors',
              item.id === selectedId
                ? 'border-accent-border bg-accent-soft font-medium'
                : 'border-border',
            )}
          >
            <span className="text-foreground min-w-0 flex-1 truncate font-medium">
              {item.prompt_preview || 'Untitled generation'}
            </span>
            <Badge variant="run-status" value={STATUS_BADGE[item.status]}>
              {item.status.replace('_', ' ')}
            </Badge>
          </button>
        </li>
      ))}
    </ul>
  );
}
