'use client';

import { useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';

import { PromptLibrary } from '@/components/prompts/prompt-library';
import { YourPrompts } from '@/components/prompts/your-prompts';
import { TooltipProvider } from '@/components/ui/tooltip';

/**
 * Prompts screen (design.md §9.4, sidebar "Prompts") — the single prompts
 * surface.
 *
 * Read view by default: the read-only, score-annotated view of the active
 * prompt configuration (prompts grouped by topic with expandable rows and
 * per-prompt / per-topic Visibility Score derived from persisted audit
 * evidence). "Manage prompts" mode swaps in the full management workspace
 * (add, import, review proposed/archived, AI generation) without leaving the
 * page. The mode follows the canonical `?mode=manage` deep link; the read
 * view's manage controls are plain links to that URL. In-page toggle buttons
 * set a local override so no navigation is
 * needed. The page title renders in the top bar (F5), so there is no in-page
 * header.
 */
function PromptsScreen() {
  const modeParam = useSearchParams().get('mode');
  // Local override for the in-page toggle buttons; null = follow the URL.
  const [override, setOverride] = useState<boolean | null>(null);
  const managing = override ?? modeParam === 'manage';

  // Exiting manage mode selects the read view and clears the URL param, so the
  // read view's `/prompts?mode=manage` links keep working (they would
  // otherwise self-reference the current URL and no-op). Shallow URL
  // bookkeeping only — `router.replace` sent this through the App Router and
  // remounted the read view on top of the local state change.
  const exitManage = () => {
    setOverride(null);
    if (modeParam === 'manage') window.history.replaceState(null, '', '/prompts');
  };

  if (managing) {
    return (
      <TooltipProvider>
        <PromptLibrary onDoneManaging={exitManage} />
      </TooltipProvider>
    );
  }

  return (
    <div className="grid gap-[var(--workspace-gap)]">
      <YourPrompts />
    </div>
  );
}

export default function PromptsPage() {
  // `PromptsScreen` reads `useSearchParams` (`?mode=manage` deep link), so it
  // sits under `<Suspense>` per Next's CSR-bailout requirement.
  return (
    <Suspense>
      <PromptsScreen />
    </Suspense>
  );
}
