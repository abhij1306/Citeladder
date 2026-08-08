'use client';

import { useQuery } from '@tanstack/react-query';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { ReactNode } from 'react';

import { Alert } from '@/components/ui/alert';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import {
  EvidencePanel,
  JourneysPanel,
  KnowledgePanel,
  OverviewPanel,
  SchemaPanel,
} from '@/components/site-intelligence/panels';
import { siteIntelligenceQueries } from '@/lib/api/site-intelligence';

/**
 * The Site Intelligence workspace (plan §11).
 *
 * Six panels over ONE crawl, with the panel mirrored to `?panel=` so a view is
 * linkable and survives a refresh. Exactly one panel renders at a time — every
 * count and score comes from the server projection, and the panels share the
 * crawl the caller selected rather than each resolving their own.
 *
 * Pages is not re-implemented here: it is the existing Site Health inventory
 * screen, passed in as `pagesPanel`, because a second pages table would be a
 * second answer to the same question.
 */
const PANELS = [
  'overview',
  'pages',
  'knowledge',
  'schema',
  'journeys',
  'evidence',
] as const;

export type IntelligencePanel = (typeof PANELS)[number];

/**
 * Pages, not Overview.
 *
 * Overview only says anything once a crawl has finished and produced a
 * snapshot. Pages is the discover -> select -> analyze lifecycle, which is what
 * the route has always shown and what a user is doing when they arrive.
 * Defaulting to Overview put a "no snapshot yet" notice in front of a running
 * crawl and hid its controls behind a tab.
 */
const DEFAULT_PANEL: IntelligencePanel = 'pages';

const PANEL_LABELS: Record<IntelligencePanel, string> = {
  overview: 'Overview',
  pages: 'Pages',
  knowledge: 'Knowledge',
  schema: 'Schema',
  journeys: 'Journeys',
  evidence: 'Evidence',
};

const PANEL_PARAM = 'panel';

function resolvePanel(value: string | null): IntelligencePanel {
  return PANELS.includes(value as IntelligencePanel)
    ? (value as IntelligencePanel)
    : DEFAULT_PANEL;
}

export function SiteIntelligenceWorkspace({
  projectId,
  crawlId,
  pagesPanel,
}: Readonly<{
  projectId: string;
  crawlId?: string;
  /** The existing Site Health pages/inventory screen. */
  pagesPanel: ReactNode;
}>) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const panel = resolvePanel(searchParams.get(PANEL_PARAM));

  const overviewQuery = useQuery(siteIntelligenceQueries.overview(projectId, crawlId));

  const selectPanel = (next: IntelligencePanel) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set(PANEL_PARAM, next);
    // `replace` + `scroll: false`: switching panels is not a navigation the
    // back button should have to walk through, and the page must not jump.
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  };

  const tabs = (
    <div
      role="tablist"
      aria-label="Site Intelligence panels"
      className="border-border-subtle flex flex-wrap gap-1 border-b"
    >
      {PANELS.map((id) => {
        const selected = id === panel;
        return (
          <button
            key={id}
            type="button"
            role="tab"
            id={`si-tab-${id}`}
            aria-selected={selected}
            aria-controls={`si-panel-${id}`}
            onClick={() => selectPanel(id)}
            className={cn(
              'text-sm -mb-px border-b-2 px-3 py-2 transition-colors',
              selected
                ? 'border-accent text-foreground'
                : 'text-muted hover:text-foreground border-transparent',
            )}
          >
            {PANEL_LABELS[id]}
          </button>
        );
      })}
    </div>
  );

  const body = () => {
    if (panel === 'pages') {
      return pagesPanel;
    }
    if (overviewQuery.isLoading) {
      return <Card className="text-muted p-[var(--card-padding)] text-sm">Loading…</Card>;
    }
    if (overviewQuery.isError) {
      return <Alert tone="danger">Could not load Site Intelligence. Please refresh.</Alert>;
    }
    const overview = overviewQuery.data;
    if (!overview) {
      return null;
    }
    // Two DIFFERENT absences, kept apart. "No snapshot yet" is a crawl that has
    // not finished; "no pack" is a finished crawl with no industry vocabulary,
    // which still produced generic Site Health evidence. Collapsing them into
    // one empty state would tell a user to wait for something that will never
    // arrive.
    if (!overview.available) {
      return (
        <Alert tone="info">
          {overview.reason ??
            'This crawl has not produced an intelligence snapshot yet. Finish the crawl to see coverage and scores.'}
        </Alert>
      );
    }
    if (!overview.packed) {
      return (
        <Alert tone="warning">
          No industry pack applied to this crawl, so there is no vocabulary for roles, questions, or
          journeys. Generic Site Health evidence is still available under Pages. Set the
          project&apos;s industry and start a new crawl to enable Site Intelligence.
        </Alert>
      );
    }

    const props = { projectId, crawlId, overview };
    switch (panel) {
      case 'knowledge':
        return <KnowledgePanel {...props} />;
      case 'schema':
        return <SchemaPanel {...props} />;
      case 'journeys':
        return <JourneysPanel {...props} />;
      case 'evidence':
        return <EvidencePanel {...props} />;
      default:
        return <OverviewPanel {...props} />;
    }
  };

  return (
    <div className="grid gap-4" data-testid="site-intelligence-workspace">
      {tabs}
      <div role="tabpanel" id={`si-panel-${panel}`} aria-labelledby={`si-tab-${panel}`}>
        {body()}
      </div>
    </div>
  );
}
