'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { ContentScreen } from '@/components/content/content-screen';
import { BrandKnowledgeScreen } from '@/components/knowledge-base/brand-knowledge-screen';
import { LayerTabs, type LayerTab } from '@/components/layout/layer-tabs';

/**
 * Content Intelligence (§7.3) — the layer route.
 *
 * The pipeline is insight → brief → generated draft → automatic validation →
 * user edits → SAVE → verification. Generation is the shipped end: the
 * existing screen keeps its `?opportunity_id=` contract, which is how an
 * insight hands off to a draft.
 *
 * Facts is the project-facts surface (§9.3 renames "Brand knowledge" to
 * "Facts"; the `/knowledge-base` route persists, only the label changed).
 * Briefs, validation and verification land with stage 4.
 */
const TABS: readonly LayerTab[] = [
  { id: 'generate', label: 'Generate' },
  { id: 'facts', label: 'Facts' },
  { id: 'briefs', label: 'Briefs' },
  { id: 'verification', label: 'Verification' },
];

const PENDING_COPY: Record<string, string> = {
  briefs:
    'Immutable briefs built from an insight and the facts behind it. Rebuilding creates a new version rather than editing in place.',
  verification:
    'What was observed after a recrawl. Descriptive only — it does not claim the content caused a change.',
};

function ContentTabPanel() {
  const searchParams = useSearchParams();
  const tab = searchParams.get('tab') ?? 'generate';

  if (tab === 'generate') {
    return <ContentScreen opportunityId={searchParams.get('opportunity_id')} />;
  }
  if (tab === 'facts') return <BrandKnowledgeScreen />;

  return (
    <div className="border-border-subtle bg-panel rounded-lg border p-8">
      <p className="text-foreground text-sm font-medium">Not yet available</p>
      <p className="text-muted mt-2 max-w-[60ch] text-sm leading-relaxed">{PENDING_COPY[tab]}</p>
    </div>
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
