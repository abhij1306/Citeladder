import Link from 'next/link';
import { ChevronDown, Inbox, Package } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardEyebrow, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dropdown,
  DropdownContent,
  DropdownLabel,
  DropdownRadioGroup,
  DropdownRadioItem,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { CompetitorProductVisibilityEntry, ProductVisibilityEntry } from '@/lib/api/types';
import { engineLabel } from '@/lib/providers/catalog';
import {
  RANK_BUCKET_LABELS,
  RANK_BUCKET_ORDER,
  formatAvgRank,
  formatPercent,
  priceRelationDisplay,
} from '@/lib/products/catalog';
import type { useProductVisibilityQueries } from '@/lib/products/use-products-screen';
import { cn } from '@/lib/utils';

const RANK_SEGMENT_CLASS: Record<(typeof RANK_BUCKET_ORDER)[number], string> = {
  top_1: 'bg-success',
  top_2_3: 'bg-info',
  top_4_5: 'bg-warning',
  rank_6_plus: 'bg-danger',
  unranked: 'bg-border-bold',
};

type VisibilityQueries = ReturnType<typeof useProductVisibilityQueries>;

export function SummaryCard({
  label,
  value,
  caption,
}: Readonly<{ label: string; value: string; caption: string }>) {
  return (
    <Card>
      <CardContent className="grid gap-1">
        <CardEyebrow>{label}</CardEyebrow>
        <p className="font-mono text-xl tabular-nums">{value}</p>
        <p className="text-muted text-xs">{caption}</p>
      </CardContent>
    </Card>
  );
}

type RankingRow =
  | { kind: 'own'; entry: ProductVisibilityEntry }
  | { kind: 'competitor'; entry: CompetitorProductVisibilityEntry };

export function RankingsCard({
  title,
  description,
  rows,
  kind,
}: Readonly<{
  title: string;
  description: string;
  rows: ProductVisibilityEntry[] | CompetitorProductVisibilityEntry[];
  kind: 'own' | 'competitor';
}>) {
  const normalized: RankingRow[] = rows.map((entry) => ({ kind, entry }) as RankingRow);
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="grid gap-1">
          <CardTitle>{title}</CardTitle>
          <p className="text-secondary text-sm">{description}</p>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {normalized.length === 0 ? (
          <p className="text-secondary p-[var(--card-padding)] text-sm">
            Nothing measured here in the selected run.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                <TableHead>Product</TableHead>
                <TableHead>Mentions</TableHead>
                <TableHead>SOV</TableHead>
                <TableHead>Win rate</TableHead>
                <TableHead className="min-w-35">Rank distribution</TableHead>
                <TableHead>Avg rank</TableHead>
                <TableHead className="min-w-50">Price relation</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {normalized.map((row, index) => (
                <RankingTableRow key={rowKey(row)} row={row} position={index + 1} />
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function rowKey(row: RankingRow): string {
  if (row.kind === 'own') {
    return row.entry.product_id ?? `own:${row.entry.sku}:${row.entry.name}`;
  }
  return (
    row.entry.competitor_product_id ?? `competitor:${row.entry.competitor_name}:${row.entry.name}`
  );
}

function RankingTableRow({ row, position }: Readonly<{ row: RankingRow; position: number }>) {
  const { entry } = row;
  const subtitle = row.kind === 'own' ? row.entry.sku : row.entry.competitor_name;
  return (
    <TableRow>
      <TableCell numeric className="text-muted">
        {position}
      </TableCell>
      <TableCell className="max-w-70 min-w-45">
        <div className="grid gap-0.5">
          <span className="flex items-center gap-2">
            {row.kind === 'own' && row.entry.product_id ? (
              <Link
                href={`/products/${row.entry.product_id}`}
                className="text-foreground hover:text-accent-text truncate font-medium transition-colors"
              >
                {entry.name}
              </Link>
            ) : (
              <span className="text-foreground truncate font-medium">{entry.name}</span>
            )}
            {row.kind === 'own' ? (
              <Badge variant="status" value="info">
                You
              </Badge>
            ) : null}
          </span>
          {subtitle ? <span className="text-muted truncate text-xs">{subtitle}</span> : null}
        </div>
      </TableCell>
      <TableCell numeric className="text-secondary">
        {entry.mention_count}
      </TableCell>
      <TableCell numeric className="text-secondary">
        {formatPercent(entry.sov_share)}
      </TableCell>
      <TableCell numeric className="text-secondary">
        {formatPercent(entry.win_rate)}
      </TableCell>
      <TableCell>
        <RankDistributionBar distribution={entry.rank_distribution} />
      </TableCell>
      <TableCell numeric className="text-secondary">
        {formatAvgRank(entry.avg_rank)}
      </TableCell>
      <TableCell>
        <PriceRelationCell entry={entry} />
      </TableCell>
    </TableRow>
  );
}

/**
 * The Price relation cell: persisted match/higher/lower counts as labelled
 * badges (Match = success, Higher = warning, Lower = info). An analyzer-v1
 * row with persisted mismatches reads `Direction unavailable` with the muted
 * mismatch count — direction is NEVER inferred for v1 data. Nothing
 * verifiable renders the null placeholder.
 */
function PriceRelationCell({
  entry,
}: Readonly<{
  entry: ProductVisibilityEntry | CompetitorProductVisibilityEntry;
}>) {
  const display = priceRelationDisplay(entry);
  if (display.kind === 'empty') return <span className="text-subtle">—</span>;
  if (display.kind === 'unavailable') {
    return (
      <span className="flex items-center gap-2">
        <Badge variant="status" value="warning">
          Direction unavailable
        </Badge>
        <span className="text-muted mono text-xs">{display.mismatch}</span>
      </span>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-1">
      {display.match > 0 ? (
        <Badge variant="status" value="success">
          Match {display.match}
        </Badge>
      ) : null}
      {display.higher > 0 ? (
        <Badge variant="status" value="warning">
          Higher {display.higher}
        </Badge>
      ) : null}
      {display.lower > 0 ? (
        <Badge variant="status" value="info">
          Lower {display.lower}
        </Badge>
      ) : null}
    </span>
  );
}

/**
 * Compact stacked bar of the persisted rank buckets (Top 1 → 6+ → unranked).
 * Each segment carries a `title` with its bucket label + count so the value
 * is never color-only.
 */
function RankDistributionBar({ distribution }: Readonly<{ distribution: Record<string, number> }>) {
  const total = RANK_BUCKET_ORDER.reduce((sum, key) => sum + (distribution[key] ?? 0), 0);
  if (total === 0) return <span className="text-subtle">—</span>;
  return (
    <div
      className="bg-neutral-bg flex h-2 w-full overflow-hidden rounded-full"
      role="img"
      aria-label={RANK_BUCKET_ORDER.map(
        (key) => `${RANK_BUCKET_LABELS[key]}: ${distribution[key] ?? 0}`,
      ).join(', ')}
    >
      {RANK_BUCKET_ORDER.map((key) => {
        const count = distribution[key] ?? 0;
        if (count === 0) return null;
        return (
          <span
            key={key}
            title={`${RANK_BUCKET_LABELS[key]}: ${count}`}
            className={cn('h-full', RANK_SEGMENT_CLASS[key])}
            style={{ width: `${(count / total) * 100}%` }}
          />
        );
      })}
    </div>
  );
}

export function VisibilitySkeleton() {
  return (
    <div className="grid gap-4" aria-hidden>
      <Skeleton className="h-8 w-96" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24 w-full" />
        ))}
      </div>
      <Skeleton className="h-56 w-full" />
    </div>
  );
}

/** Run picker shared by the toolbar and the selected-run 404 empty state. */
export function RunSelectorDropdown({
  runOptions,
  activeRunId,
  selectRun,
}: Readonly<{
  runOptions: VisibilityQueries['runOptions'];
  activeRunId: string | null;
  selectRun: (id: string | null) => void;
}>) {
  const activeRun = runOptions.find((run) => run.id === activeRunId) ?? null;
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <Button variant="secondary" size="sm" aria-label="Select run">
          <span className="text-muted">Run:</span>
          <span className="font-medium">{activeRun?.label ?? 'Latest'}</span>
          <ChevronDown className="text-muted size-3" aria-hidden />
        </Button>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownLabel>Runs</DropdownLabel>
        <DropdownRadioGroup value={activeRunId ?? '__latest__'}>
          <DropdownRadioItem value="__latest__" onSelect={() => selectRun(null)}>
            Latest
          </DropdownRadioItem>
          {runOptions.map((run) => (
            <DropdownRadioItem key={run.id} value={run.id} onSelect={() => selectRun(run.id)}>
              {run.label}
            </DropdownRadioItem>
          ))}
        </DropdownRadioGroup>
      </DropdownContent>
    </Dropdown>
  );
}

/** D2 state (a): no completed run has product metrics yet — guide to runs. */
export function NoAuditEmpty({
  onGoToCatalog,
  selectedRun = false,
}: Readonly<{ onGoToCatalog: () => void; selectedRun?: boolean }>) {
  return (
    <EmptyState
      icon={Inbox}
      heading="No product visibility yet"
      description={
        selectedRun
          ? 'No product metrics in this run — pick another run, or launch one that scores your catalog.'
          : 'Run an audit to measure how answer engines rank and price your products — share of voice, rank distribution, and price accuracy appear here when it completes.'
      }
      action={
        <>
          <Button variant="ghost" size="md" onClick={onGoToCatalog}>
            <Package className="size-4" aria-hidden />
            Go to Catalog
          </Button>
          <Button asChild variant="primary" size="md">
            <Link href="/runs">View runs</Link>
          </Button>
        </>
      }
    />
  );
}

/**
 * D2 state (b): the selected run completed but recorded ZERO product
 * mentions in this slice (COM-1/COM-2). Explain why (the answers never
 * named a catalog product) and give the two concrete fixes — prompts that
 * name the products, and catalog aliases that match how people ask —
 * instead of the old wall of zeros.
 */
export function NoMentionsEmpty({
  engineParam,
  onGoToCatalog,
}: Readonly<{
  engineParam: string | undefined;
  onGoToCatalog: () => void;
}>) {
  // Name the active slice so a filtered-to-zero view never reads as "the
  // whole run had nothing".
  const slice = engineParam ? ` on ${engineLabel(engineParam)}` : '';
  return (
    <EmptyState
      icon={Package}
      heading="This run recorded no product mentions"
      description={`The selected run completed, but none of its answers${slice} mentioned a product from your catalog.`}
      action={
        <>
          <Button asChild variant="primary" size="md">
            <Link href="/prompts">Add product-named prompts</Link>
          </Button>
          <Button variant="ghost" size="md" onClick={onGoToCatalog}>
            Check catalog aliases
          </Button>
        </>
      }
    />
  );
}
