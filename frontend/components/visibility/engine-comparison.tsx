import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import type { RankingRow, Visibility } from '@/lib/api/types';
import {
  PLACEHOLDER,
  engineLabel,
  formatRate,
  sortedRankings,
  visibleEngines,
  type VisibilityFilters,
} from '@/lib/visibility/dashboard';

/**
 * Per-model comparison + Share-of-answers (design.md §9.6).
 *
 * The per-engine breakdown is a dense TABLE (one row per logical engine:
 * visibility, brand mentions, owned citations, search used, responses) rather
 * than a grid of score rings — the flat language reserves rings for surfaces
 * where the ring itself carries the data, and a table compares models far
 * better. Alongside it are the brand-vs-competitor share bars: the brand row
 * takes the flat accent fill (`bg-accent`), competitors a muted fill on the
 * well track.
 *
 * Honors the engine filter; the table shows an explicit empty message when the
 * filtered set is empty.
 *
 * This component keeps its original DATA logic — only the rendering changed.
 */
export function EngineComparison({
  visibility,
  filter,
}: Readonly<{ visibility: Visibility; filter: VisibilityFilters['engine'] }>) {
  const engines = visibleEngines(visibility, filter);

  return (
    <div className="grid gap-3 xl:grid-cols-[1.55fr_1fr]">
      <Card>
        <CardHeader bordered>
          <CardTitle>By model</CardTitle>
          <CardDescription>How each AI model sees your brand in this run</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {engines.length === 0 ? (
            <p className="text-secondary p-[var(--card-padding)] text-sm">
              No model results match the current filter.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Model</TableHead>
                  <TableHead numeric>Visibility</TableHead>
                  <TableHead numeric>Brand mentions</TableHead>
                  <TableHead numeric>Owned citations</TableHead>
                  <TableHead numeric>Search used</TableHead>
                  <TableHead numeric>Responses</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {engines.map((engine) => (
                  <TableRow key={engine.logical_engine}>
                    <TableCell className="text-foreground font-medium">
                      {engineLabel(engine.logical_engine)}
                    </TableCell>
                    <TableCell numeric className="mono text-foreground font-medium">
                      {engine.visibility_score === null
                        ? PLACEHOLDER
                        : `${Math.round(engine.visibility_score)}%`}
                    </TableCell>
                    <TableCell numeric className="mono text-secondary">
                      {formatRate(engine.brand_mention_rate)}
                    </TableCell>
                    <TableCell numeric className="mono text-secondary">
                      {formatRate(engine.owned_citation_rate)}
                    </TableCell>
                    <TableCell numeric className="mono text-secondary">
                      {formatRate(engine.search_use_rate)}
                    </TableCell>
                    <TableCell numeric className="mono text-secondary">
                      {engine.total_completed}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <ShareOfVoiceCard visibility={visibility} />
    </div>
  );
}

function ShareOfVoiceCard({ visibility }: Readonly<{ visibility: Visibility }>) {
  const rows = sortedRankings(visibility.rankings).filter((row) => (row.mention_count ?? 0) > 0);
  // Derived from the same source as the bars/numerals. Rows with unavailable
  // share data remain present in the accessible summary without inventing a
  // percentage for their zero-width visual bar.
  const shares = rows.map((row) => {
    const pct = sovPercent(row);
    return pct === null ? `${row.name} share unavailable` : `${row.name} ${pct}%`;
  });
  const summary = shares.length > 0 ? shares.join(', ') : 'No data';

  return (
    <Card>
      <CardHeader>
        <CardTitle>Share of answers</CardTitle>
        <CardDescription>Mentions across models</CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-secondary text-sm">{PLACEHOLDER} No mentions recorded for this run.</p>
        ) : (
          <div
            // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- The labelled multi-row visualization is one composite image, not a replaceable img resource.
            role="img"
            aria-label={`Share of voice: ${summary}`}
            className="grid gap-4"
          >
            {rows.map((row) => (
              <ShareOfVoiceRow
                key={`${row.is_brand ? 'brand' : 'competitor'}-${row.name}`}
                row={row}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** Clamped 0–100 bar/announced percent for a SOV row; null when the run has no share data. */
function sovPercent(row: RankingRow): number | null {
  return row.share_of_voice === null
    ? null
    : Math.max(0, Math.min(100, Math.round(row.share_of_voice * 100)));
}

function ShareOfVoiceRow({ row }: Readonly<{ row: RankingRow }>) {
  const pct = sovPercent(row) ?? 0;
  return (
    <div className="grid grid-cols-[92px_1fr_44px] items-center gap-3">
      <span
        className={cn(
          'truncate text-sm',
          row.is_brand ? 'text-foreground font-medium' : 'text-secondary font-medium',
        )}
      >
        {row.name}
      </span>
      <span className="bg-well h-2 overflow-hidden rounded-full">
        <span
          className={cn(
            'block h-full rounded-full',
            row.is_brand ? 'bg-accent' : 'bg-foreground/20',
          )}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span
        className={cn(
          'mono text-right text-xs',
          row.is_brand ? 'text-foreground' : 'text-secondary',
        )}
      >
        {formatRate(row.share_of_voice)}
      </span>
    </div>
  );
}
