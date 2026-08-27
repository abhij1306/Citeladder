import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { BrandLogo } from '@/components/ui/brand-logo';
import { scoreBand, scoreBandText } from '@/components/ui/score-band';
import { Sparkline } from '@/components/ui/sparkline';
import { cn } from '@/lib/utils';
import type { RankingRow } from '@/lib/api/types';
import { PLACEHOLDER, formatRate } from '@/lib/visibility/dashboard';

/** Shared empty state for a rankings table with no rows. */
export const NO_RANKINGS_MESSAGE = 'No brand or competitor mentions were recorded for this run.';

/**
 * Shared brand-vs-competitor rankings table (design.md §9.6), used by both the
 * selected-run Competitors card and the trend-mode ranking-history cards.
 *
 * Columns are `#`, Brand (logo + name + a "You" chip on the own brand),
 * Visibility% (mono + score-band colour), Share%, Sentiment and
 * Position — the last two render the explicit not-measured state
 * (decision B-2). The user's own row is `highlight`ed.
 *
 * `history` is optional real per-brand visibility series (see
 * `brandVisibilityHistory`). When supplied, a brand with at least two readable
 * points gets a sparkline; brands without one render an empty cell rather than
 * an invented flat line, and the column disappears entirely when no history is
 * available at all.
 */
export function RankingRowsTable({
  rows,
  history,
}: Readonly<{
  rows: readonly RankingRow[];
  history?: ReadonlyMap<string, number[]>;
}>) {
  const showTrend = Boolean(
    history && rows.some((row) => (history.get(row.name)?.length ?? 0) > 1),
  );

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-10">#</TableHead>
          <TableHead>Brand</TableHead>
          <TableHead numeric>Visibility</TableHead>
          {showTrend ? <TableHead className="w-20">Trend</TableHead> : null}
          <TableHead numeric>Share</TableHead>
          <TableHead numeric>Sentiment</TableHead>
          <TableHead numeric>Position</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => {
          const visibilityPct =
            row.mention_rate === null ? null : Math.round(row.mention_rate * 100);
          const bandClass =
            visibilityPct === null ? 'text-muted' : scoreBandText[scoreBand(visibilityPct)];
          return (
            <TableRow
              key={`${row.is_brand ? 'brand' : 'competitor'}-${row.name}`}
              highlight={row.is_brand}
            >
              <TableCell numeric className="text-muted">
                {index + 1}
              </TableCell>
              <TableCell>
                <span className="flex items-center gap-2">
                  <BrandLogo
                    name={row.name}
                    logoUrl={row.logo_url}
                    websiteUrl={row.website_url}
                    size="sm"
                  />
                  <span className="text-foreground font-medium">{row.name}</span>
                  {row.is_brand ? (
                    <span className="bg-well text-secondary text-2xs inline-flex items-center rounded-sm px-1.5 py-0.5 font-medium">
                      You
                    </span>
                  ) : null}
                </span>
              </TableCell>
              <TableCell numeric className={cn('mono font-medium', bandClass)}>
                {formatRate(row.mention_rate)}
              </TableCell>
              {showTrend ? (
                <TableCell>
                  {(history?.get(row.name)?.length ?? 0) > 1 ? (
                    <Sparkline
                      values={history!.get(row.name)!}
                      tone={row.is_brand ? 'brand' : 'muted'}
                      label={`${row.name} visibility trend`}
                    />
                  ) : null}
                </TableCell>
              ) : null}
              <TableCell numeric className="mono text-foreground">
                {formatRate(row.share_of_voice)}
              </TableCell>
              <TableCell numeric className="mono text-muted">
                {PLACEHOLDER}
              </TableCell>
              <TableCell numeric className="mono text-muted">
                {PLACEHOLDER}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
