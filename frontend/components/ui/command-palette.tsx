'use client';

import * as DialogPrimitive from '@radix-ui/react-dialog';
import { CornerDownLeft, Search, type LucideIcon } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';

import { NAV_GROUPS } from '@/components/layout/nav-items';
import { BrandLogo } from '@/components/ui/brand-logo';
import { Button } from '@/components/ui/button';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import { ICONS } from '@/lib/icons';
import { useProjectContext } from '@/lib/project/project-context';
import { cn } from '@/lib/utils';

/**
 * CommandPalette — ⌘K / Ctrl+K navigation for the authed shell.
 *
 * Keyboard-first velocity is the point: every nav destination and every
 * project in the workspace is reachable without leaving the home row. The
 * top-bar search is the pointer affordance for the same thing.
 *
 * Deliberately NOT built on components/ui/dialog.tsx — that wrapper owns a
 * title/description/close header, which a palette must not have (the input is
 * the header). It uses the same Radix primitive and the same scrim/surface
 * tokens, so the two stay visually consistent.
 *
 * Filtering is a plain substring match over label + group. There is no fuzzy
 * matcher and no index: the corpus is ~12 nav items plus the workspace's
 * projects, where subsequence matching mostly produces surprising ranking for
 * no measurable gain.
 */
type Command = {
  id: string;
  label: string;
  group: string;
  /** Nav destinations carry their canonical glyph; projects render a brand logo. */
  icon?: LucideIcon;
  logoUrl?: string | null;
  hint?: string;
  run: () => void;
};

/** Chrome shared by the empty state and each row, so heights never drift. */
const ROW = 'flex w-full items-center gap-2.5 rounded-sm px-3 text-left text-sm h-9';

/**
 * Results keep ONE flat order for the keyboard cursor, but render grouped.
 * Rebuilding sections from that flat list (rather than grouping first and
 * flattening for keys) is what keeps the highlighted row and the Enter target
 * the same element — the two orders can never drift apart.
 */
function toSections(results: readonly Command[]) {
  const sections: { group: string; rows: { command: Command; index: number }[] }[] = [];
  results.forEach((command, index) => {
    const last = sections.at(-1);
    if (last?.group === command.group) last.rows.push({ command, index });
    else sections.push({ group: command.group, rows: [{ command, index }] });
  });
  return sections;
}

export function CommandPalette() {
  const router = useRouter();
  const { projects, activeProjectId, setActiveProjectId } = useProjectContext();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const listboxId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Where focus goes when the palette closes. Radix restores focus to its own
  // Trigger, but the ⌘K path has no trigger, so without this the caller loses
  // their place in the page and focus falls back to <body>.
  const returnFocusTo = useRef<HTMLElement | null>(null);

  const restoreFocus = useCallback(() => {
    const target = returnFocusTo.current;
    returnFocusTo.current = null;
    // The element may have unmounted while the palette was open — switching
    // project re-renders the shell — so check it is still in the document.
    if (target?.isConnected) target.focus();
  }, []);

  // Opening resets the palette. Done in the handler, not an effect — the reset
  // is caused by the interaction, not by state outside React.
  const setOpenState = useCallback((next: boolean) => {
    setOpen(next);
    if (next) {
      setQuery('');
      setActive(0);
    }
  }, []);

  // ⌘K / Ctrl+K toggles from anywhere. Bound on keydown so it beats the
  // browser's own find-in-page on the platforms that map ⌘K.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      // Modifier first, then `key`. This handler runs on EVERY keystroke in the
      // app, so the cheap test should gate the string work — and `event.key` is
      // optional on a programmatically constructed KeyboardEvent (browser
      // extensions and IMEs dispatch these), where reading `.toLowerCase()` off
      // it threw "Cannot read properties of undefined".
      if (!(event.metaKey || event.ctrlKey) || event.key?.toLowerCase() !== 'k') return;
      event.preventDefault();
      if (open) {
        setOpen(false);
        return;
      }

      // Capture the caller's position before the dialog steals focus.
      const activeEl = document.activeElement;
      returnFocusTo.current = activeEl instanceof HTMLElement ? activeEl : null;
      setQuery('');
      setActive(0);
      setOpen(true);
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open]);

  const commands = useMemo<Command[]>(() => {
    const navigation = NAV_GROUPS.flatMap((group) =>
      group.items.map((item) => ({
        id: `nav:${item.href}`,
        label: item.label,
        group: group.title,
        icon: item.icon,
        run: () => router.push(item.href),
      })),
    );

    const settingsCommands: Command[] = [
      {
        id: 'nav:/settings?tab=integrations',
        label: 'Integrations',
        group: 'Settings',
        icon: ICONS.setup,
        run: () => router.push('/settings?tab=integrations'),
      },
      {
        id: 'nav:/settings?tab=providers',
        label: 'Providers',
        group: 'Settings',
        icon: ICONS.settings,
        run: () => router.push('/settings?tab=providers'),
      },
      {
        id: 'nav:/settings',
        label: 'Settings',
        group: 'Settings',
        icon: ICONS.settings,
        run: () => router.push('/settings'),
      },
    ];

    // Switching project re-scopes the API client's workspace header, so this
    // is a genuine action rather than a link.
    const projectCommands = projects.map((project) => ({
      id: `project:${project.id}`,
      // brand_name is required by projectSchema, so there is no fallback to
      // guard here; ProjectSwitcher shows the same label.
      label: project.brand_name,
      group: 'Switch project',
      logoUrl: project.brand?.logo_url,
      hint: project.id === activeProjectId ? 'Current' : undefined,
      run: () => setActiveProjectId(project.id),
    }));

    return [...navigation, ...settingsCommands, ...projectCommands];
  }, [router, projects, activeProjectId, setActiveProjectId]);

  const results = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return commands;
    return commands.filter((command) =>
      `${command.label} ${command.group}`.toLowerCase().includes(needle),
    );
  }, [commands, query]);

  // The cursor is CLAMPED during render rather than corrected in an effect:
  // typing shrinks the result set, and storing an index that is briefly out of
  // range would render one frame with nothing selected before a corrective
  // pass fixed it. Deriving it means there is no such frame.
  const activeIndex = active >= results.length ? 0 : active;

  // Keep the highlighted row visible when moving by keyboard past the fold.
  // Feature-detected: jsdom does not implement scrollIntoView, and this is
  // presentation-only — losing it must never break selection.
  useEffect(() => {
    const row = listRef.current?.querySelector('[data-active="true"]');
    if (row instanceof HTMLElement && typeof row.scrollIntoView === 'function') {
      row.scrollIntoView({ block: 'nearest' });
    }
  }, [activeIndex]);

  const runCommand = useCallback((command: Command | undefined) => {
    if (!command) return;
    setOpen(false);
    command.run();
  }, []);

  // Movement is relative to the CLAMPED index, so wrapping stays correct even
  // on the render right after a filter shrank the list.
  function onInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!results.length) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((activeIndex + 1) % results.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((activeIndex - 1 + results.length) % results.length);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      runCommand(results[activeIndex]);
    }
  }

  return (
    <>
      {/* The top bar's pointer affordance for the same palette. It records
          itself as the focus target for the same reason the ⌘K path does —
          this button is not a Radix Trigger, so nothing else would. */}
      <Button
        variant="ghost"
        size="sm"
        onClick={(event) => {
          returnFocusTo.current = event.currentTarget;
          setOpenState(true);
        }}
        aria-label="Search or jump to"
        aria-keyshortcuts="Meta+K Control+K"
        className="bg-panel hover:bg-well border-border/70 text-muted hover:text-foreground h-9 w-full justify-start rounded-sm border px-3 text-left shadow-xs transition-colors"
      >
        <Search className="text-muted size-4 shrink-0" aria-hidden strokeWidth={1.75} />
        <span className="min-w-0 truncate text-sm font-normal">Search or jump to…</span>
        <kbd className="bg-background-alt border-border/60 text-muted ms-auto hidden shrink-0 rounded-sm border px-1.5 py-0.5 text-xs font-medium sm:inline">
          ⌘K
        </kbd>
      </Button>

      <DialogPrimitive.Root open={open} onOpenChange={setOpenState}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="bg-overlay-scrim z-overlay fixed inset-0" />
          <DialogPrimitive.Content
            // Radix requires a Title for the dialog's accessible name and
            // warns when one is absent. The palette has no visible heading —
            // its input is the header — so the title is screen-reader only.
            // `aria-describedby={undefined}` opts out of the description Radix
            // otherwise looks for, which this dialog deliberately lacks.
            aria-describedby={undefined}
            onOpenAutoFocus={(event) => {
              event.preventDefault();
              inputRef.current?.focus();
            }}
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              restoreFocus();
            }}
            className="border-border/60 bg-elevated/95 shadow-modal-value z-modal fixed top-24 left-1/2 flex max-h-3/5 w-full max-w-xl -translate-x-1/2 flex-col overflow-hidden overscroll-contain rounded-[var(--radius-overlay)] border backdrop-blur-xl focus:outline-none"
          >
            <DialogPrimitive.Title className="sr-only">Command palette</DialogPrimitive.Title>
            <div className="border-border/60 flex items-center gap-3 border-b px-4">
              <Search className="text-muted size-4 shrink-0" aria-hidden strokeWidth={1.75} />
              <input
                ref={inputRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onInputKeyDown}
                placeholder="Search or jump to…"
                aria-label="Search commands"
                aria-controls={listboxId}
                aria-activedescendant={
                  results[activeIndex] ? `${listboxId}-${results[activeIndex].id}` : undefined
                }
                // The input is the only focusable thing in the palette and is
                // focused the whole time it is open, so the global
                // `:focus-visible` outline would draw a permanent blue ring
                // around the header for no information. `!` is needed because
                // that rule is unlayered and would otherwise beat a utility.
                className="text-foreground placeholder:text-muted h-11 min-w-0 flex-1 bg-transparent text-sm outline-none focus-visible:outline-none!"
              />
              <kbd className="border-border/60 text-muted shrink-0 rounded-md border px-1.5 py-0.5 font-mono text-xs">
                esc
              </kbd>
            </div>

            <div
              ref={listRef}
              id={listboxId}
              role="listbox"
              aria-label="Commands"
              className="content-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain p-1"
            >
              {results.length === 0 ? (
                <p className={cn(ROW, 'text-muted')}>No matches for “{query}”</p>
              ) : (
                toSections(results).map((section) => (
                  <div key={section.group} className="mb-1 last:mb-0">
                    <p className={cn(eyebrowClasses, 'px-2 pt-2 pb-1')}>{section.group}</p>
                    {section.rows.map(({ command, index }) => {
                      const isActive = index === activeIndex;
                      const Icon = command.icon;
                      return (
                        <button
                          key={command.id}
                          id={`${listboxId}-${command.id}`}
                          type="button"
                          role="option"
                          aria-selected={isActive}
                          data-active={isActive}
                          onMouseMove={() => setActive(index)}
                          onClick={() => runCommand(command)}
                          className={cn(
                            ROW,
                            'transition-colors',
                            isActive
                              ? 'bg-accent-subtle text-accent-text'
                              : 'text-secondary hover:bg-background-alt',
                          )}
                        >
                          {Icon ? (
                            <Icon
                              className={cn('size-4 shrink-0', !isActive && 'text-muted')}
                              aria-hidden
                              strokeWidth={1.75}
                            />
                          ) : (
                            <BrandLogo
                              name={command.label}
                              logoUrl={command.logoUrl}
                              size="xs"
                              className="bg-foreground text-background"
                            />
                          )}
                          <span className="min-w-0 flex-1 truncate">{command.label}</span>
                          {command.hint ? (
                            <span className="text-muted shrink-0 text-xs">{command.hint}</span>
                          ) : null}
                          {isActive ? (
                            <CornerDownLeft
                              className="text-muted size-4 shrink-0"
                              aria-hidden
                              strokeWidth={1.75}
                            />
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                ))
              )}
            </div>

            {/* Keyboard legend — the palette is a keyboard surface first, so
                it states its own controls rather than assuming they are known. */}
            <div className="border-border/60 text-muted flex shrink-0 items-center gap-4 border-t px-4 py-2.5 text-xs font-medium">
              <span className="flex items-center gap-1.5">
                <kbd className="border-border/60 bg-well text-2xs rounded-md border px-1.5 py-0.5 font-mono">
                  ↑
                </kbd>
                <kbd className="border-border/60 bg-well text-2xs rounded-md border px-1.5 py-0.5 font-mono">
                  ↓
                </kbd>
                navigate
              </span>
              <span className="flex items-center gap-1.5">
                <kbd className="border-border/60 bg-well text-2xs rounded-md border px-1.5 py-0.5 font-mono">
                  ↵
                </kbd>
                select
              </span>
            </div>
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>
    </>
  );
}
