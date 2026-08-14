'use client';

import { useRef, type KeyboardEvent, type ReactNode } from 'react';

import { tabItemClasses, tabListClasses } from '@/components/ui/tabs';

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
  idPrefix,
  panel,
}: Readonly<{
  tabs: readonly { id: T; label: string }[];
  activeTab: T;
  onSelectTab: (tab: T) => void;
  ariaLabel: string;
  /** Unique id stem for the tab/panel ARIA wiring (`{idPrefix}-tab-{id}`). */
  idPrefix: string;
  /** The rendered content of the active panel (the parent owns composition). */
  panel: ReactNode;
}>) {
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const activeIndex = tabs.findIndex((tab) => tab.id === activeTab);

  function focusTab(index: number) {
    const tab = tabs[index];
    if (!tab) return;
    onSelectTab(tab.id);
    tabRefs.current[tab.id]?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const last = tabs.length - 1;
    switch (event.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        event.preventDefault();
        focusTab(activeIndex >= last ? 0 : activeIndex + 1);
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        event.preventDefault();
        focusTab(activeIndex <= 0 ? last : activeIndex - 1);
        break;
      case 'Home':
        event.preventDefault();
        focusTab(0);
        break;
      case 'End':
        event.preventDefault();
        focusTab(last);
        break;
      default:
        break;
    }
  }

  const tabId = (tab: T) => `${idPrefix}-tab-${tab}`;
  const panelId = (tab: T) => `${idPrefix}-panel-${tab}`;

  return (
    <div className="grid gap-4">
      <div
        role="tablist"
        aria-label={ariaLabel}
        aria-orientation="horizontal"
        className={tabListClasses}
      >
        {tabs.map((tab) => {
          const selected = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              ref={(node) => {
                tabRefs.current[tab.id] = node;
              }}
              type="button"
              role="tab"
              id={tabId(tab.id)}
              aria-selected={selected}
              aria-controls={selected ? panelId(tab.id) : undefined}
              tabIndex={selected ? 0 : -1}
              onClick={() => onSelectTab(tab.id)}
              onKeyDown={onKeyDown}
              className={tabItemClasses(selected)}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={panelId(activeTab)}
        aria-labelledby={tabId(activeTab)}
        tabIndex={0}
        className="focus-ring outline-none"
      >
        {panel}
      </div>
    </div>
  );
}
