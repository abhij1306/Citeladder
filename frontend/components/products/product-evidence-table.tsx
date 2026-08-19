'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ChevronLeft, Info } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardEyebrow,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { productsApi } from '@/lib/api/products';
import { queryKeys } from '@/lib/api/query-keys';
import { runsApi } from '@/lib/api/runs';
import type { Product, ProductEvidenceItem } from '@/lib/api/types';
import {
  PRODUCT_EVIDENCE_SUB_TABS,
  formatPrice,
  type ProductEngineFilter,
  type ProductEvidenceSubTab,
} from '@/lib/products/catalog';
import { engineLabel } from '@/lib/providers/catalog';
import { isDashboardStatus } from '@/lib/visibility/dashboard';

import { NestedTabs } from '@/components/ui/nested-tabs';

import { DestinationEvidenceTable } from './product-evidence-destination-card';
import { EngineFilterDropdown } from './engine-filter-dropdown';

/** Newest-window size for the evidence request (backend max 500). */
const EVIDENCE_LIMIT = 100;

/**
 * Product evidence drill-down (`/products/[productId]`): the persisted
 * evidence for one catalog product, split by `evidence_kind` into a nested
 * segmented tablist (Mentions | Attributes | Destinations — local state,
 * never in the URL). ONE bounded newest-first query feeds all three panels;
 * the active kind filters client-side. Mentions keep rank/price/relation and
 * the source-execution link; attribute rows show dimension, group, the exact
 * matched text, and offset; destination rows show merchant, kind, the
 * backend-sanitized URL, and any price shown at the destination. Every
 * panel keeps the 100-row limit, its truncation notice, and `—` for nulls.
 */
export function ProductEvidenceTable({
  product,
  backHref = '/products',
}: Readonly<{ product: Product; backHref?: string }>) {
  const [engine, setEngine] = useState<ProductEngineFilter>('all');
  const [subTab, setSubTab] = useState<ProductEvidenceSubTab>('mentions');
  const engineParam = engine === 'all' ? undefined : engine;
  // Surface participates in the evidence key/request; the drill-down always
  // reads the measurement surface ('') — surface discovery lives on the
  // Visibility projection (`available_surfaces`), which this page never loads.
  const surface = '';

  const evidenceQuery = useQuery({
    queryKey: queryKeys.products.evidence(product.id, {
      engine: engineParam ?? null,
      surface,
      limit: EVIDENCE_LIMIT,
    }),
    queryFn: ({ signal }) =>
      productsApi.getProductEvidence(
        product.id,
        { engine: engineParam, surface, limit: EVIDENCE_LIMIT },
        { signal },
      ),
  });

  const items = evidenceQuery.data?.items ?? [];

  // Run-awareness for the empty copy (D2/COM-3): "mentions appear once a run
  // completes" is wrong when runs HAVE completed — the copy must say so.
  //
  // Gated to the ONE case that consumes it: the Mentions sub-tab, with the
  // evidence query settled and no mentions in it. Ungated, every visit to the
  // drill-down fetched the project's whole audit list to pick between two
  // sentences that were usually never rendered at all.
  const mentionsAreEmpty =
    evidenceQuery.isSuccess && !items.some((item) => item.evidence_kind === 'product_mention');
  const auditsQuery = useQuery({
    queryKey: queryKeys.runs.list({ project_id: product.project_id }),
    queryFn: ({ signal }) => runsApi.listAudits({ project_id: product.project_id }, { signal }),
    enabled: subTab === 'mentions' && mentionsAreEmpty,
  });
  const hasCompletedRun = (auditsQuery.data ?? []).some((audit) => isDashboardStatus(audit.status));
  const truncated = evidenceQuery.data?.truncated ?? false;

  return (
    <div className="grid gap-4">
      <div>
        <Button asChild variant="ghost" size="sm">
          <Link href={backHref}>
            <ChevronLeft className="size-4" aria-hidden />
            Products
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-3">
          <div className="grid gap-1">
            <CardEyebrow>Product</CardEyebrow>
            <CardTitle>{product.name}</CardTitle>
            <p className="text-secondary text-sm">
              <span className="font-mono text-xs">{product.sku}</span>
              {' · '}
              {formatPrice(product.price, product.currency)}
              {' · '}
              {product.completeness.present}/{product.completeness.total} attributes
            </p>
          </div>
          <EngineFilterDropdown engine={engine} onChange={setEngine} />
        </CardHeader>
      </Card>

      {evidenceQuery.isLoading ? (
        <Card>
          <CardContent className="grid gap-3" aria-hidden>
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-2/3" />
          </CardContent>
        </Card>
      ) : evidenceQuery.isError ? (
        <Alert tone="danger">
          Could not load this product&apos;s evidence.{' '}
          <button type="button" className="underline" onClick={() => evidenceQuery.refetch()}>
            Retry
          </button>
        </Alert>
      ) : (
        <NestedTabs
          tabs={PRODUCT_EVIDENCE_SUB_TABS}
          activeTab={subTab}
          onSelectTab={setSubTab}
          ariaLabel="Evidence kinds"
          idPrefix="product-evidence"
          panel={
            subTab === 'attributes' ? (
              <AttributeEvidenceCard
                items={items.filter((item) => item.evidence_kind === 'attribute_mention')}
                truncated={truncated}
                engineParam={engineParam}
              />
            ) : subTab === 'destinations' ? (
              <DestinationEvidenceCard
                items={items.filter((item) => item.evidence_kind === 'buyer_destination')}
                truncated={truncated}
                engineParam={engineParam}
              />
            ) : (
              <MentionEvidenceCard
                items={items.filter((item) => item.evidence_kind === 'product_mention')}
                truncated={truncated}
                engineParam={engineParam}
                hasCompletedRun={hasCompletedRun}
              />
            )
          }
        />
      )}
    </div>
  );
}

type EvidenceKindCardProps = Readonly<{
  items: ProductEvidenceItem[];
  truncated: boolean;
  engineParam: string | undefined;
}>;

function EvidenceCardShell({
  eyebrow,
  title,
  description,
  truncated,
  empty,
  emptyCopy,
  notice,
  children,
}: Readonly<{
  eyebrow: string;
  title: string;
  description: string;
  truncated: boolean;
  empty: boolean;
  emptyCopy: string;
  /** Truncation notice shown under the table when the window was cut. */
  notice: string;
  children: React.ReactNode;
}>) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="grid gap-1">
          <CardEyebrow>{eyebrow}</CardEyebrow>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        {truncated && !empty ? (
          <Badge variant="status" value="warning">
            Truncated
          </Badge>
        ) : null}
      </CardHeader>
      <CardContent className="p-0">
        {empty ? (
          <p className="text-secondary p-[var(--card-padding)] text-sm">{emptyCopy}</p>
        ) : (
          <>
            {children}
            {truncated ? (
              <div className="border-border-subtle text-muted flex items-center gap-2 border-t px-4 py-2 text-xs">
                <Info className="size-4 shrink-0" aria-hidden />
                <span>{notice}</span>
              </div>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function MentionEvidenceCard({
  items,
  truncated,
  engineParam,
  hasCompletedRun,
}: EvidenceKindCardProps & Readonly<{ hasCompletedRun: boolean }>) {
  return (
    <EvidenceCardShell
      eyebrow="Evidence · Mentions"
      title="Where this product was mentioned"
      description="Answer executions that mentioned the product, with rank, the extracted price and the character offset in the answer text."
      truncated={truncated}
      empty={items.length === 0}
      emptyCopy={
        engineParam
          ? `No persisted mentions of this product on ${engineLabel(engineParam)} yet.`
          : hasCompletedRun
            ? 'Completed runs recorded no mentions of this product — check that its name and aliases match how people ask about it.'
            : 'No mentions of this product yet — they appear here once a run completes.'
      }
      notice={`Showing the first ${EVIDENCE_LIMIT} mentions for this product; older mentions are truncated.`}
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Engine</TableHead>
            <TableHead className="min-w-55">Prompt</TableHead>
            <TableHead>Rank</TableHead>
            <TableHead>Price mentioned</TableHead>
            <TableHead>vs catalog</TableHead>
            <TableHead>Offset</TableHead>
            <TableHead className="text-right">Execution</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <MentionEvidenceRow key={item.evidence_id} item={item} />
          ))}
        </TableBody>
      </Table>
    </EvidenceCardShell>
  );
}

function MentionEvidenceRow({ item }: Readonly<{ item: ProductEvidenceItem }>) {
  return (
    <TableRow>
      <TableCell>
        <Badge variant="neutral">{engineLabel(item.logical_engine)}</Badge>
      </TableCell>
      <TableCell className="max-w-80">
        <span className="text-foreground line-clamp-2 block text-sm">{item.prompt_text}</span>
        <span className="text-muted text-xs">
          #{item.prompt_index} · rep {item.repetition}
        </span>
      </TableCell>
      <TableCell numeric className="text-secondary">
        {item.rank_position !== null ? `#${item.rank_position}` : '—'}
      </TableCell>
      <TableCell numeric className="text-secondary">
        {item.price_value !== null ? (
          <span title={item.price_text}>{formatPrice(item.price_value, item.price_currency)}</span>
        ) : (
          '—'
        )}
      </TableCell>
      <TableCell>
        <PriceRelationBadge item={item} />
      </TableCell>
      <TableCell numeric className="text-secondary">
        {item.first_offset !== null ? item.first_offset : '—'}
      </TableCell>
      <TableCell className="text-right">
        <Link
          href={`/runs/${item.audit_id}?execution=${item.task_id}`}
          className="text-accent-text text-sm hover:underline"
        >
          Open
        </Link>
      </TableCell>
    </TableRow>
  );
}

/**
 * The vs-catalog verdict: the persisted item-level `price_relation`
 * (Match/Higher/Lower) when the analyzer recorded one; otherwise the v1
 * boolean fallback (Match/Mismatch — direction is never inferred); `—` when
 * the price was not verifiable.
 */
function PriceRelationBadge({ item }: Readonly<{ item: ProductEvidenceItem }>) {
  if (item.price_relation === 'match') {
    return (
      <Badge variant="status" value="success">
        Match
      </Badge>
    );
  }
  if (item.price_relation === 'higher') {
    return (
      <Badge variant="status" value="warning">
        Higher
      </Badge>
    );
  }
  if (item.price_relation === 'lower') {
    return (
      <Badge variant="status" value="info">
        Lower
      </Badge>
    );
  }
  if (item.price_matches_catalog === null) return <span className="text-subtle">—</span>;
  // v1 fallback: the verdict was computed against the audit-time FROZEN
  // catalog price, so quoting the live price here could contradict it after
  // a post-audit price edit — the badge stands alone.
  return item.price_matches_catalog ? (
    <Badge variant="status" value="success">
      Match
    </Badge>
  ) : (
    <Badge variant="status" value="warning">
      Mismatch
    </Badge>
  );
}

function AttributeEvidenceCard({ items, truncated, engineParam }: EvidenceKindCardProps) {
  return (
    <EvidenceCardShell
      eyebrow="Evidence · Attributes"
      title="Attribute mentions for this product"
      description="Exact attribute text matched in the answer windows around mentions of this product, grouped by dimension and group."
      truncated={truncated}
      empty={items.length === 0}
      emptyCopy={
        engineParam
          ? `No persisted attribute mentions of this product on ${engineLabel(engineParam)} yet.`
          : 'No persisted attribute mentions of this product yet.'
      }
      notice={`Showing the first ${EVIDENCE_LIMIT} attribute mentions for this product; the rest are truncated.`}
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Engine</TableHead>
            <TableHead className="min-w-55">Prompt</TableHead>
            <TableHead>Dimension</TableHead>
            <TableHead>Group</TableHead>
            <TableHead className="min-w-55">Matched text</TableHead>
            <TableHead>Offset</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.evidence_id}>
              <TableCell>
                <Badge variant="neutral">{engineLabel(item.logical_engine)}</Badge>
              </TableCell>
              <TableCell className="max-w-80">
                <span className="text-foreground line-clamp-2 block text-sm">
                  {item.prompt_text}
                </span>
                <span className="text-muted text-xs">
                  #{item.prompt_index} · rep {item.repetition}
                </span>
              </TableCell>
              <TableCell className="text-secondary">{item.attribute_dimension ?? '—'}</TableCell>
              <TableCell className="text-secondary">{item.attribute_group ?? '—'}</TableCell>
              <TableCell className="max-w-80">
                {item.attribute_text !== null ? (
                  <span className="text-foreground line-clamp-2 block text-sm">
                    &ldquo;{item.attribute_text}&rdquo;
                  </span>
                ) : (
                  <span className="text-subtle">—</span>
                )}
              </TableCell>
              <TableCell numeric className="text-secondary">
                {item.attribute_offset !== null ? item.attribute_offset : '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </EvidenceCardShell>
  );
}

function DestinationEvidenceCard({ items, truncated, engineParam }: EvidenceKindCardProps) {
  return (
    <EvidenceCardShell
      eyebrow="Evidence · Destinations"
      title="Where answers send buyers for this product"
      description="Sanitized merchant links surfaced beside mentions of this product, with the destination kind and any price shown at the destination."
      truncated={truncated}
      empty={items.length === 0}
      emptyCopy={
        engineParam
          ? `No persisted buyer destinations for this product on ${engineLabel(engineParam)} yet.`
          : 'No persisted buyer destinations for this product yet.'
      }
      notice={`Showing the first ${EVIDENCE_LIMIT} buyer destinations for this product; the rest are truncated.`}
    >
      <DestinationEvidenceTable items={items} />
    </EvidenceCardShell>
  );
}
