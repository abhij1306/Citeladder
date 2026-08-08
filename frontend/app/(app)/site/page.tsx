'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { LayerTabs, type LayerTab } from '@/components/layout/layer-tabs';
import { CorpusPanel } from '@/components/site/corpus-panel';
import { SiteHealthScreen } from '@/components/site-health/site-health-screen';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useActiveProject } from '@/lib/project/project-context';
import { siteHealthQueries } from '@/lib/api/site-health';
import { useQuery } from '@tanstack/react-query';

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
  facts: 'Entities, assertions and relations with effective dates and contradiction groups.',
  schema: 'Observed JSON-LD beside pack expectations, as a comparison rather than a score.',
  journeys: 'Stage coverage against the pack template.',
  evidence: 'Crawl attempts, artifacts and fetch failures.',
};

/** Corpus needs the latest crawl; the pages projection is keyed by crawl. */
function Corpus() {
  const project = useActiveProject();
  const crawlsQuery = useQuery({
    ...siteHealthQueries.crawls({ project_id: project?.id ?? '', limit: 1 }),
    enabled: Boolean(project?.id),
  });

  if (!project?.id) {
    return <p className="text-muted text-sm">Select a project to see its corpus.</p>;
  }
  // Request status comes first: an in-flight or failed crawl lookup is not the
  // same fact as "no crawl has run", and collapsing the three into the empty
  // message is exactly the state-conflation §7.4 calls out. `isLoading` rather
  // than `isPending` — a disabled query is pending forever, and the guard above
  // is what actually covers that case.
  if (crawlsQuery.isLoading) return <p className="text-muted text-sm">Loading corpus…</p>;
  if (crawlsQuery.isError) {
    return <p className="text-muted text-sm">The corpus could not be loaded.</p>;
  }

  const crawlId = crawlsQuery.data?.items[0]?.id;
  if (!crawlId) {
    return <p className="text-muted text-sm">No crawl has run for this project yet.</p>;
  }
  return <CorpusPanel crawlId={crawlId} />;
}

function SiteTabPanel() {
  const tab = useSearchParams().get('tab') ?? 'pages';

  if (tab === 'pages') return <SiteHealthScreen />;
  if (tab === 'corpus') return <Corpus />;

  return (
    <div className="bg-panel shadow-card rounded-lg p-8">
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
