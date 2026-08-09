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

function isContentPanel(value: string | null): value is ContentPanel {
  return CONTENT_PANEL_IDS.some((id) => id === value);
}

function ContentTabPanel() {
  const searchParams = useSearchParams();
  const requested = searchParams.get('tab');
  const panel = isContentPanel(requested) ? requested : 'strategy';

  return (
    <ContentIntelligenceScreen
      panel={panel}
      opportunityId={searchParams.get('opportunity_id')}
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
