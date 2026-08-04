'use client';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardEyebrow,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import type {
  AttributionDelta,
  AttributionMethodMetrics,
  UnattributedMetrics,
} from '@/lib/api/types';
import {
  ATTRIBUTION_DELTA_LABEL,
  ATTRIBUTION_METHOD_LABELS,
  REDUCED_GRANULARITY_COPY,
  formatConversionRate,
  formatMoney,
  formatSignedInt,
  formatSignedMoney,
  formatSignedPercent,
  unattributedSummary,
  type AttributionCurrencyBlock,
} from '@/lib/products/attribution';
import { formatPercent } from '@/lib/products/catalog';

/**
 * Attribution › Overview: one ISO currency block of the deterministic
 * snapshot. A1 and A2 render side by side and are NEVER merged or summed;
 * the backend-projected delta and the unattributed remainder are their own
 * cards. The reduced-granularity alert appears only when A1 persisted the
 * fallback. Null metrics render `—` everywhere.
 */
export function AttributionMethodComparison({
  block,
}: Readonly<{ block: AttributionCurrencyBlock }>) {
  const reduced = block.a1?.reduced_granularity === true;
  return (
    <div className="grid gap-4">
      {reduced ? (
        <Alert tone="warning">
          {REDUCED_GRANULARITY_COPY} Item rows below are not per-AI-source data.
        </Alert>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        <MethodCard method="ga4_platform_attributed" metrics={block.a1} currency={block.currency} />
        <MethodCard method="order_referrer" metrics={block.a2} currency={block.currency} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <DeltaCard delta={block.delta} />
        {block.unattributed ? <UnattributedCard unattributed={block.unattributed} /> : null}
      </div>
    </div>
  );
}

/** One metric row (label + persisted value) inside a method/delta card. */
function MetricRow({ label, value }: Readonly<{ label: string; value: React.ReactNode }>) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-muted text-sm">{label}</span>
      <span className="text-foreground mono text-sm tabular-nums">{value}</span>
    </div>
  );
}

const METHOD_DESCRIPTIONS = {
  ga4_platform_attributed:
    'Deterministic, aggregate/surface-level. Sessions attributed by GA4 to AI sources.',
  order_referrer:
    'Deterministic, per-order and per-SKU. Orders whose referrer resolves to an AI source.',
} as const;

const METHOD_NOT_CONNECTED_NOTES = {
  ga4_platform_attributed:
    'Search Console and Analytics 4 share one Google OAuth grant in Settings › Integrations.',
  order_referrer: 'CiteLadder requests read-only order scopes and never stores customer data.',
} as const;

function MethodCard({
  method,
  metrics,
  currency,
}: Readonly<{
  method: keyof typeof ATTRIBUTION_METHOD_LABELS;
  metrics: AttributionMethodMetrics | undefined;
  currency: string | null;
}>) {
  const state = metrics?.state ?? 'no_data';
  const available = state === 'available' && metrics !== undefined;
  const totals = metrics?.totals ?? null;

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="grid gap-1">
          <CardTitle>{ATTRIBUTION_METHOD_LABELS[method]}</CardTitle>
          {available ? (
            <p className="text-foreground mono text-lg font-semibold tabular-nums">
              {formatMoney(totals?.revenue, currency)} revenue
            </p>
          ) : null}
          <CardDescription>{METHOD_DESCRIPTIONS[method]}</CardDescription>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-1">
          {available ? (
            <Badge variant="status" value="info">
              Deterministic
            </Badge>
          ) : null}
          {available && metrics.reduced_granularity ? (
            <Badge variant="status" value="warning">
              Reduced granularity
            </Badge>
          ) : null}
          {state === 'not_connected' ? (
            <Badge variant="status" value="warning">
              Not connected
            </Badge>
          ) : null}
          {state === 'no_data' ? <Badge variant="neutral">No data</Badge> : null}
        </div>
      </CardHeader>
      <CardContent className="grid gap-2">
        <MetricRow
          label="Revenue"
          value={available ? formatMoney(totals?.revenue, currency) : '—'}
        />
        <MetricRow
          label="Orders"
          value={available && totals?.orders !== null ? totals?.orders : '—'}
        />
        <MetricRow
          label="Average order value"
          value={available ? formatMoney(totals?.average_order_value, currency) : '—'}
        />
        {method === 'ga4_platform_attributed' ? (
          <>
            <MetricRow
              label="Conversion rate"
              value={available ? formatConversionRate(totals?.conversion_rate) : '—'}
            />
            <MetricRow
              label="Data granularity"
              value={
                available
                  ? metrics.source_granularity === 'default_channel_group'
                    ? 'Item × default channel'
                    : 'Item × session source'
                  : '—'
              }
            />
          </>
        ) : (
          <>
            <MetricRow label="Conversion rate" value="—" />
            <MetricRow
              label="Referrer coverage"
              value={available ? formatPercent(metrics.coverage_rate) : '—'}
            />
          </>
        )}
        {state === 'not_connected' ? (
          <p className="text-muted border-border-subtle mt-2 border-t pt-3 text-xs">
            {METHOD_NOT_CONNECTED_NOTES[method]}
          </p>
        ) : null}
        {state === 'no_data' ? (
          <p className="text-muted border-border-subtle mt-2 border-t pt-3 text-xs">
            No persisted attribution rows for this window yet.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function DeltaCard({ delta }: Readonly<{ delta: AttributionDelta | undefined }>) {
  const comparable = delta?.state === 'comparable';
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="grid gap-1">
          <CardEyebrow>Cross-check between methods</CardEyebrow>
          <CardTitle>{ATTRIBUTION_DELTA_LABEL}</CardTitle>
          <CardDescription>
            A1 and A2 measure the same orders through different evidence. They are never added
            together.
          </CardDescription>
        </div>
        {delta && !comparable ? <Badge variant="neutral">Not comparable</Badge> : null}
      </CardHeader>
      <CardContent className="grid gap-2">
        <MetricRow
          label="Revenue"
          value={comparable ? formatSignedMoney(delta?.revenue, delta?.currency ?? null) : '—'}
        />
        <MetricRow label="Orders" value={comparable ? formatSignedInt(delta?.orders) : '—'} />
        <MetricRow
          label="Average order value"
          value={
            comparable
              ? formatSignedMoney(delta?.average_order_value, delta?.currency ?? null)
              : '—'
          }
        />
        <MetricRow
          label="Conversion rate"
          value={comparable ? formatSignedPercent(delta?.conversion_rate) : '—'}
        />
      </CardContent>
    </Card>
  );
}

function UnattributedCard({ unattributed }: Readonly<{ unattributed: UnattributedMetrics }>) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="grid gap-1">
          <CardTitle>Unattributed</CardTitle>
          <p className="text-foreground text-sm font-medium">
            {unattributedSummary(unattributed.orders, unattributed.order_share)}
          </p>
          <CardDescription>
            These orders stay unattributed. No AI source is inferred for them.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="grid gap-2">
        <MetricRow label="Orders" value={unattributed.orders} />
        <MetricRow label="Order share" value={formatPercent(unattributed.order_share)} />
        <MetricRow
          label="Revenue"
          value={formatMoney(unattributed.revenue, unattributed.currency)}
        />
      </CardContent>
    </Card>
  );
}
