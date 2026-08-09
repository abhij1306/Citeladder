'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';

import {
  ContentIntelligenceScreen,
  type ContentPanel,
} from '@/components/content/content-intelligence-screen';
import { LayerTabs, type LayerTab } from '@/components/layout/layer-tabs';

const CONTENT_PANEL_IDS = [
  'strategy',
  'inventory',
  'briefs',
  'drafts',
  'revisions',
  'verification',
] as const satisfies readonly ContentPanel[];
const CONTENT_PANEL_LABELS: Record<ContentPanel, string> = {
  strategy: 'Strategy',
  inventory: 'Inventory',
  briefs: 'Briefs',
  drafts: 'Drafts',
  revisions: 'Revisions',
  verification: 'Verification',
};
const TABS: readonly LayerTab[] = CONTENT_PANEL_IDS.map((id) => ({
  id,
  label: CONTENT_PANEL_LABELS[id],
}));
const CONTENT_PANEL_ID_SET: ReadonlySet<string> = new Set(CONTENT_PANEL_IDS);

function isContentPanel(value: string | null): value is ContentPanel {
  return value !== null && CONTENT_PANEL_ID_SET.has(value);
}

function defaultPanel(opportunityId: string | null): ContentPanel {
  return opportunityId ? 'drafts' : 'strategy';
}

function ContentTabPanel() {
  const searchParams = useSearchParams();
  const requested = searchParams.get('tab');
  const opportunityId = searchParams.get('opportunity_id');
  const panel = isContentPanel(requested) ? requested : defaultPanel(opportunityId);

  return (
    <ContentIntelligenceScreen
      panel={panel}
      opportunityId={opportunityId}
      revisionId={searchParams.get('revision_id')}
    />
  );
}

export default function ContentPage() {
  return (
    <div className="grid gap-6">
      <Suspense fallback={null}>
        <LayerTabs tabs={TABS} />
        <ContentTabPanel />
      </Suspense>
      <Link
        href="/agent?task=explain&objective=Explain%20the%20current%20Content%20strategy%20and%20its%20limitations."
        className="text-accent-text justify-self-start text-sm font-medium underline-offset-2 hover:underline"
      >
        Explain this strategy with the Growth Agent
      </Link>
    </div>
  );
}
