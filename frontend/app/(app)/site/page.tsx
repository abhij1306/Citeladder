'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { LayerTabs, type LayerTab } from '@/components/layout/layer-tabs';
import { SiteHealthScreen } from '@/components/site-health/site-health-screen';
import { TooltipProvider } from '@/components/ui/tooltip';

/**
 * Site Intelligence (§7.2) — the layer route.
 *
 * Sub-surfaces are tabs here rather than sidebar children (§4). Pages is the
 * shipped surface, backed by the existing site-health projections. Corpus,
 * Facts, Schema, Journeys and Evidence are the §7.2 surfaces whose backend
 * lands in stages 1–2; they render as declared-but-empty rather than being
 * hidden, so the shape of the layer is legible while it fills in.
 *
 * `/site-health` still resolves — §3's migration rule keeps every deep link
 * working, and route moves happen per slice with a redirect, not as a cutover.
 */
const TABS: readonly LayerTab[] = [
  { id: 'pages', label: 'Pages' },
  { id: 'corpus', label: 'Corpus' },
  { id: 'facts', label: 'Facts' },
  { id: 'schema', label: 'Schema' },
  { id: 'journeys', label: 'Journeys' },
  { id: 'evidence', label: 'Evidence' },
];

const PENDING_COPY: Record<string, string> = {
  corpus: 'Disposition per document — analyzed, inventory-only, or excluded, each with its reason.',
  facts: 'Entities, assertions and relations with effective dates and contradiction groups.',
  schema: 'Observed JSON-LD beside pack expectations, as a comparison rather than a score.',
  journeys: 'Stage coverage against the pack template.',
  evidence: 'Crawl attempts, artifacts and fetch failures.',
};

function SiteTabPanel() {
  const tab = useSearchParams().get('tab') ?? 'pages';

  if (tab === 'pages') return <SiteHealthScreen />;

  return (
    <div className="border-border-subtle bg-panel rounded-lg border p-8">
      <p className="text-foreground text-sm font-medium">Not yet available</p>
      <p className="text-muted mt-2 max-w-[60ch] text-sm leading-relaxed">
        {PENDING_COPY[tab] ?? 'This surface is not available yet.'}
      </p>
    </div>
  );
}

export default function SitePage() {
  return (
    <TooltipProvider>
      <div className="flex flex-col gap-6">
        <Suspense fallback={null}>
          <LayerTabs tabs={TABS} />
          <SiteTabPanel />
        </Suspense>
      </div>
    </TooltipProvider>
  );
}
