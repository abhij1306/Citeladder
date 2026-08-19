import { Badge } from '@/components/ui/badge';
import type { RunStatusValue } from '@/components/ui/badge-variants';
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
      className="bg-panel shadow-card border-border/70 flex flex-col gap-3.5 rounded-sm border p-5 sm:p-6"
    >
      <div className="border-border/60 grid gap-1 border-b pb-3">
        <span className="text-muted text-xs font-semibold tracking-wider uppercase">History</span>
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
  if (items.length === 0)
    return <p className="text-muted py-4 text-center text-sm">No generations yet.</p>;
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
                ? 'border-accent-border bg-accent-soft/50 font-medium'
                : 'border-border/60',
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
