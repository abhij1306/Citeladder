'use client';

import type { ReactNode } from 'react';

import { TabPanel, Tabs } from '@/components/ui/tabs';
import { VISIBILITY_TABS, type VisibilityTab } from '@/lib/visibility/dashboard';

/**
 * Accessible three-tab navigation for the Visibility workspace (WAI-ARIA tabs).
 *
 * Exposes exactly Trends, Mentions & Citations, and Query Fanout. The tablist
 * implements roving tabindex, `aria-selected`, and
 * keyboard Arrow/Home/End navigation with focus transfer + automatic
 * activation; only the active panel is rendered as the primary section, wired
 * to its tab via `aria-controls` / `aria-labelledby`.
 *
 * URL synchronization (`?tab=`) and per-tab query orchestration live in the
 * parent `visibility-dashboard.tsx`; this component is a controlled view.
 *
 * On narrow viewports the tablist becomes a horizontally scrollable single row
 * (`overflow-x-auto` + `flex-nowrap`) with visible focus/selection states.
 * Rendered as the ADS underline tablist (components/ui/tabs.tsx), not the
 * segmented pill — the pill recipe remains only for non-tablist switches.
 */
export function VisibilityTabs({
  activeTab,
  onSelectTab,
  panel,
}: Readonly<{
  activeTab: VisibilityTab;
  onSelectTab: (tab: VisibilityTab) => void;
  /** The rendered content of the active panel (the parent owns composition). */
  panel: ReactNode;
}>) {
  return (
    <div className="grid gap-4">
      <Tabs
        value={activeTab}
        onValueChange={onSelectTab}
        items={VISIBILITY_TABS.map((tab) => ({ value: tab.id, label: tab.label }))}
        ariaLabel="Visibility views"
      >
        <TabPanel value={activeTab} className="focus-ring">
          {panel}
        </TabPanel>
      </Tabs>
    </div>
  );
}
