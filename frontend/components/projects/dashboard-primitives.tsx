import { ArrowDown, ArrowUp, GripVertical } from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import type { CommandCenter, Opportunity } from '@/lib/api/types';
import { availabilityLabel } from '@/lib/format';
import { cn } from '@/lib/utils';

export function metricValue(value: number | null, suffix = '') {
  return value === null
    ? availabilityLabel('not_measured')
    : `${Number.isInteger(value) ? value : value.toFixed(1)}${suffix}`;
}

export function deltaLabel(delta: number | null, inverse = false) {
  if (delta === null) return 'No comparable run';
  const display = inverse ? -delta : delta;
  return `${display > 0 ? '+' : ''}${display.toFixed(1)} vs previous`;
}

export function CommandCenterSkeleton() {
  return (
    <div className="grid gap-4" aria-hidden>
      <Skeleton className="h-16 w-full" />
      <div className="grid gap-3 md:grid-cols-3">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
      <Skeleton className="h-52 w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  );
}

export function StateMetric({
  label,
  value,
  delta,
  suffix,
  inverse,
}: Readonly<{
  label: string;
  value: number | null;
  delta: number | null;
  suffix?: string;
  inverse?: boolean;
}>) {
  const positive = delta !== null && (inverse ? delta < 0 : delta > 0);
  return (
    <div className="flex min-h-[112px] flex-col justify-between p-[var(--card-padding)]">
      <p className={eyebrowClasses}>{label}</p>
      <div className="my-2">
        {value === null ? (
          <UnavailableValue state="not_measured" />
        ) : (
          <p className="font-display text-foreground text-3xl leading-none font-medium tracking-[-0.03em] tabular-nums">
            {metricValue(value, suffix)}
          </p>
        )}
      </div>
      <p
        className={cn(
          'text-xs font-medium tabular-nums',
          delta === null ? 'text-muted' : positive ? 'text-success' : 'text-danger',
        )}
      >
        {deltaLabel(delta, inverse)}
      </p>
    </div>
  );
}

export function MovementChart({ movements }: Readonly<{ movements: CommandCenter['movements'] }>) {
  if (movements.length === 0)
    return (
      <div className="border-border-subtle bg-background-alt grid min-h-36 place-items-center rounded-[var(--radius-card)] border p-[var(--card-padding)] text-center">
        <p className="text-muted max-w-md text-xs">
          Movement appears after a run with the same prompts, engines, and measurement mode.
        </p>
      </div>
    );
  const ceiling = Math.max(...movements.flatMap((row) => [row.current ?? 0, row.previous ?? 0]), 1);
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {movements.map((row) => (
        <div
          key={row.label}
          className="bg-background-alt border-border-subtle rounded-[var(--radius-card)] border p-3.5"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-foreground text-xs font-medium capitalize">{row.label}</span>
            <span
              className={cn(
                'font-display text-xs font-medium tabular-nums',
                row.direction === 'positive' ? 'text-success' : 'text-danger',
              )}
            >
              {row.delta !== null ? (
                <>
                  {row.delta > 0 ? '+' : ''}
                  {row.delta}
                </>
              ) : (
                <UnavailableValue state="not_measured" />
              )}
            </span>
          </div>
          <div className="mt-3.5 flex h-14 items-end justify-center gap-2.5" aria-hidden>
            <span
              className="bg-border-strong w-6 rounded-t transition-[height]"
              style={{ height: `${Math.max(6, ((row.previous ?? 0) / ceiling) * 56)}px` }}
            />
            <span
              className="bg-accent w-6 rounded-t transition-[height]"
              style={{ height: `${Math.max(6, ((row.current ?? 0) / ceiling) * 56)}px` }}
            />
          </div>
          <p className="text-muted mt-2.5 text-center font-sans text-xs font-medium">
            Previous · Current
          </p>
        </div>
      ))}
    </div>
  );
}

export function ActionRow({
  action,
  index,
  total,
  onMove,
  onDrop,
  reorderPending,
}: Readonly<{
  action: Opportunity;
  index: number;
  total: number;
  onMove: (from: number, to: number) => void;
  onDrop: (from: number, to: number) => void;
  reorderPending: boolean;
}>) {
  const [dragging, setDragging] = useState(false);
  return (
    // oxlint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- Pointer drag is progressive enhancement; adjacent buttons provide the complete keyboard reorder path.
    <li
      draggable={!reorderPending}
      onDragStart={(event) => {
        event.dataTransfer.setData('text/plain', String(index));
        setDragging(true);
      }}
      onDragEnd={() => setDragging(false)}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        if (!reorderPending) onDrop(Number(event.dataTransfer.getData('text/plain')), index);
      }}
      className={cn(
        'border-border-subtle hover:bg-background-alt/60 grid gap-3 border-b px-4 py-3.5 transition-colors last:border-b-0 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:items-center',
        dragging && 'opacity-60',
      )}
    >
      <div className="flex items-center gap-2">
        <GripVertical className="text-muted hover:text-foreground size-4 cursor-grab" aria-hidden />
        <span className="text-muted w-5 text-center font-mono text-xs font-medium tabular-nums">
          {index + 1}
        </span>
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href={`/opportunities?selected=${action.id}`}
            className="text-foreground hover:text-accent-text text-sm font-medium transition-colors"
          >
            {action.title}
          </Link>
          {action.severity === 'critical' ? (
            <Badge variant="status" value="danger">
              {action.severity}
            </Badge>
          ) : (
            <Badge>{action.severity}</Badge>
          )}
        </div>
        <p className="text-muted mt-1 truncate text-xs">
          {action.target_label ?? 'Project-wide'} · {action.evidence_summary.count} persisted
          evidence item(s)
        </p>
      </div>
      <div className="flex items-center justify-end gap-1.5">
        <span className="text-muted font-display me-2 text-xs font-medium tabular-nums">
          {action.priority_score.toFixed(1)}
        </span>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => onMove(index, index - 1)}
          disabled={reorderPending || index === 0}
          aria-label={`Move ${action.title} up`}
        >
          <ArrowUp className="size-4" aria-hidden />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => onMove(index, index + 1)}
          disabled={reorderPending || index === total - 1}
          aria-label={`Move ${action.title} down`}
        >
          <ArrowDown className="size-4" aria-hidden />
        </Button>
      </div>
    </li>
  );
}
