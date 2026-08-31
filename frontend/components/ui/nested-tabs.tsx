'use client';

import type { ReactNode } from 'react';

import { TabPanel, Tabs } from '@/components/ui/tabs';

/**
 * Accessible shared underline tablist following the WAI-ARIA tabs pattern.
 * Roving tabindex,
 * `aria-selected`, Arrow/Home/End keyboard navigation with focus transfer +
 * automatic activation and wraparound, exactly one rendered `tabpanel`, and
 * horizontal scrolling at narrow widths. Built on the shared underline
 * recipes in `components/ui/tabs.tsx`. Controlled view: the parent owns the
 * selection state.
 */
export function NestedTabs<T extends string>({
  tabs,
  activeTab,
  onSelectTab,
  ariaLabel,
  panel,
}: Readonly<{
  tabs: readonly { id: T; label: string }[];
  activeTab: T;
  onSelectTab: (tab: T) => void;
  ariaLabel: string;
  /** The rendered content of the active panel (the parent owns composition). */
  panel: ReactNode;
}>) {
  return (
    <div className="grid gap-4">
      <Tabs
        value={activeTab}
        onValueChange={onSelectTab}
        items={tabs.map((tab) => ({ value: tab.id, label: tab.label }))}
        ariaLabel={ariaLabel}
      >
        <TabPanel value={activeTab} className="focus-ring">
          {panel}
        </TabPanel>
      </Tabs>
    </div>
  );
}
