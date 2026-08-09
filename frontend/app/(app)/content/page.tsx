'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

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

function ContentTabPanel() {
  const searchParams = useSearchParams();
  const requested = searchParams.get('tab');
  const opportunityId = searchParams.get('opportunity_id');
  const panel = isContentPanel(requested) ? requested : opportunityId ? 'drafts' : 'strategy';

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
    </div>
  );
}
