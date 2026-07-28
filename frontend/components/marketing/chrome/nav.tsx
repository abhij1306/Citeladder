'use client';

import { useQuery } from '@tanstack/react-query';
import { ChevronDown, Menu, X } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import Link from 'next/link';
import { Fragment, useEffect, useRef, useState } from 'react';

import { authApi } from '@/lib/api/auth';
import { projectsApi } from '@/lib/api/projects';
import { queryKeys } from '@/lib/api/query-keys';
import {
  DEMO_CTA,
  DEMO_HREF,
  NAV_DROPS,
  NAV_LINKS,
  type NavDropKey,
} from '@/lib/marketing-content/nav';
import { cn } from '@/lib/utils';

import { ButtonLink } from '../primitives/button';
import { Wordmark } from '../primitives/wordmark';
import { DropItemLink, MobileItemLink } from './nav-items';

const ACTIVE_PROJECT_STORAGE_KEY = 'searchify.active-project-id';
const EASE_OUT = [0.16, 1, 0.3, 1] as const;

function hasStoredActiveProject(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return Boolean(window.localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY));
  } catch {
    return false;
  }
}

const NAV_LINK =
  'text-mkt-sm text-mkt-ink-soft hover:text-mkt-ink relative z-1 inline-flex items-center gap-1.5 ' +
  'rounded-sm px-3.5 py-2.5 font-semibold transition-colors duration-200';

/**
 * Panel geometry per menu. A drop with a labelled group renders two columns —
 * the plain rows, then that group as a rail on paper. Everything else is a
 * single column. The widths are declared rather than measured because the
 * panel is anchored and clamped before it paints; a column is sized so a
 * one-line description stays on one line.
 */
const COLUMN = 304;
const DROP_LAYOUT: Record<NavDropKey, { width: number; twoColumn: boolean }> = {
  platform: { width: COLUMN, twoColumn: false },
  solutions: { width: COLUMN, twoColumn: false },
  resources: { width: COLUMN, twoColumn: false },
};

/**
 * MarketingNav — the fixed Proof chrome shared by every marketing route.
 *
 * Desktop: Platform / Solutions / Resources open hover-intent panels (hover
 * AND keyboard focus; the trigger click only ever OPENS, so a hover-open panel
 * never flickers shut under the cursor; item click, blur-out and Esc close).
 * One stable panel element stays mounted across trigger switches. Dropdown
 * contents swap immediately so the pointer target never moves or blinks.
 *
 * The lens is the deck's signature: a paper pill that glides under whichever
 * trigger the pointer is on. It is measured from the live element rather than
 * hard-coded, so it stays correct when labels change, and it is suppressed
 * under reduced motion (a pill that teleports is worse than no pill).
 *
 * ≤1024px the links collapse into a hamburger + slide-down accordions. Open
 * state is React-driven so `aria-expanded` is always truthful.
 */
export function MarketingNav() {
  const [scrolled, setScrolled] = useState(false);
  const [openDrop, setOpenDrop] = useState<NavDropKey | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openAcc, setOpenAcc] = useState<NavDropKey | null>(null);
  const [lens, setLens] = useState<{ left: number; width: number } | null>(null);
  const [panelLeft, setPanelLeft] = useState(0);
  const closeTimer = useRef<number | null>(null);
  const linksRef = useRef<HTMLDivElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const reduceMotion = useReducedMotion();

  const me = useQuery({
    queryKey: queryKeys.auth.me(),
    queryFn: ({ signal }) => authApi.me({ signal }),
    retry: false,
    refetchOnWindowFocus: false,
  });

  const { data: projects } = useQuery({
    queryKey: queryKeys.projects.list(),
    queryFn: ({ signal }) => projectsApi.listProjects({ signal }),
    enabled: me.isSuccess,
  });

  const isAuthenticated = me.isSuccess;
  const dashboardHref =
    (projects && projects.length > 0) || hasStoredActiveProject() ? '/projects' : '/onboarding';

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 10);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(
    () => () => {
      if (closeTimer.current) window.clearTimeout(closeTimer.current);
    },
    [],
  );

  useEffect(() => {
    if (!mobileOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMobileOpen(false);
        setOpenAcc(null);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [mobileOpen]);

  // Escape closes an open desktop panel from anywhere, not only from inside
  // the menu subtree. A panel opened by HOVER leaves focus wherever it was, so
  // a handler scoped to the links container would simply never hear the key.
  useEffect(() => {
    if (openDrop === null) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpenDrop(null);
      (document.activeElement as HTMLElement | null)?.blur();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [openDrop]);

  const clearDropClose = () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current);
    closeTimer.current = null;
  };
  const closeDrop = () => setOpenDrop(null);
  const openDesktopDrop = (key: NavDropKey) => {
    clearDropClose();
    setOpenDrop(key);
  };
  const scheduleDropClose = () => {
    clearDropClose();
    closeTimer.current = window.setTimeout(closeDrop, 220);
  };

  const moveLens = (element: HTMLElement) => {
    const container = linksRef.current;
    if (!container || reduceMotion) return;
    const a = element.getBoundingClientRect();
    const b = container.getBoundingClientRect();
    setLens({ left: a.left - b.left, width: a.width });
  };

  /**
   * Centre the panel beneath its top-level item, then clamp it inside the nav.
   */
  const anchorPanel = (trigger: HTMLElement, key: NavDropKey) => {
    const container = linksRef.current;
    const nav = navRef.current;
    if (!container || !nav) return;
    const triggerBox = trigger.getBoundingClientRect();
    const containerBox = container.getBoundingClientRect();
    const navBox = nav.getBoundingClientRect();
    const width = DROP_LAYOUT[key].width;
    const desired = triggerBox.left + triggerBox.width / 2 - width / 2;
    const clamped = Math.min(
      Math.max(desired, navBox.left),
      Math.max(navBox.right - width, navBox.left),
    );
    setPanelLeft(clamped - containerBox.left);
  };

  const escapeToClose = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      closeDrop();
      (document.activeElement as HTMLElement | null)?.blur();
    }
  };

  return (
    <div
      data-scrolled={scrolled ? 'true' : undefined}
      className={cn(
        'fixed inset-x-0 top-0 z-50 border-b transition-colors duration-300',
        'bg-mkt-paper-raised',
        scrolled ? 'border-mkt-line-soft' : 'border-transparent',
      )}
    >
      <nav
        ref={navRef}
        aria-label="Main navigation"
        className="h-mkt-nav max-w-mkt px-mkt-gutter mx-auto flex w-full items-center gap-4"
      >
        <Link href="/" aria-label="Searchify home" className="shrink-0">
          <Wordmark />
        </Link>

        <div
          ref={linksRef}
          className="relative mx-auto hidden items-center lg:flex"
          onMouseEnter={clearDropClose}
          onMouseLeave={() => {
            scheduleDropClose();
            setLens(null);
          }}
          onBlurCapture={(event) => {
            // The panel is a sibling of the triggers, so "did focus leave?" is
            // a question about the whole group, not about one item.
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) closeDrop();
          }}
          onKeyDown={escapeToClose}
        >
          {lens && (
            <motion.span
              layout={!reduceMotion}
              aria-hidden
              style={{ left: lens.left, width: lens.width }}
              transition={{ layout: { duration: 0.18, ease: EASE_OUT } }}
              className={cn(
                'border-mkt-line-soft bg-mkt-surface shadow-modal-value pointer-events-none rounded-sm',
                'absolute inset-y-0 border',
              )}
            />
          )}

          {NAV_DROPS.map(({ key, label, href }) => (
            <div
              key={key}
              className="relative z-1 flex items-center"
              onMouseEnter={(event) => {
                openDesktopDrop(key);
                anchorPanel(event.currentTarget, key);
                moveLens(event.currentTarget);
              }}
            >
              <Link
                href={href}
                className={cn(NAV_LINK, 'pr-1.5')}
                onFocus={(event) => {
                  const parent = event.currentTarget.parentElement;
                  if (!parent) return;
                  openDesktopDrop(key);
                  anchorPanel(parent, key);
                  moveLens(parent);
                }}
              >
                {label}
              </Link>
              <button
                type="button"
                className="text-mkt-ink-soft hover:text-mkt-ink relative z-1 grid size-7 place-items-center rounded-sm"
                aria-label={`Open ${label} menu`}
                aria-expanded={openDrop === key}
                aria-haspopup="true"
                aria-controls={openDrop === key ? `desktop-nav-panel-${key}` : undefined}
                onClick={(event) => {
                  const parent = event.currentTarget.parentElement;
                  if (!parent) return;
                  if (openDrop === key) {
                    closeDrop();
                    return;
                  }
                  openDesktopDrop(key);
                  anchorPanel(parent, key);
                }}
                onFocus={(event) => {
                  const parent = event.currentTarget.parentElement;
                  if (!parent) return;
                  openDesktopDrop(key);
                  anchorPanel(parent, key);
                  moveLens(parent);
                }}
              >
                {' '}
                <ChevronDown
                  aria-hidden
                  className={cn(
                    'size-3 transition-transform duration-300',
                    openDrop === key && 'rotate-180',
                  )}
                />
              </button>
            </div>
          ))}

          {NAV_LINKS.map(({ label, href }) => (
            <Link
              key={href}
              href={href}
              className={NAV_LINK}
              // Both pointer and keyboard arrival on a plain link must retire
              // an open panel — otherwise tabbing out of a dropdown leaves it
              // hanging over the page with nothing focused inside it.
              onMouseEnter={(event) => {
                scheduleDropClose();
                moveLens(event.currentTarget);
              }}
              onFocus={(event) => {
                scheduleDropClose();
                moveLens(event.currentTarget);
              }}
            >
              {label}
            </Link>
          ))}

          <AnimatePresence>
            {openDrop !== null && (
              <div
                role="menu"
                id={`desktop-nav-panel-${openDrop}`}
                onMouseEnter={clearDropClose}
                style={{
                  left: panelLeft,
                  width: DROP_LAYOUT[openDrop].width,
                  maxWidth: 'calc(100vw - 2rem)',
                }}
                className={cn(
                  'border-mkt-line-soft bg-mkt-surface shadow-modal-value rounded-mkt-sm absolute top-full',
                  'mt-1.5 overflow-hidden border',
                )}
              >
                <div className={cn('grid', DROP_LAYOUT[openDrop].twoColumn && 'sm:grid-cols-2')}>
                  {(NAV_DROPS.find((d) => d.key === openDrop)?.groups ?? []).map((group) =>
                    group.label ? (
                      // The labelled group is a rail on paper — a plain
                      // border-left left it reading as one long list of
                      // unrelated rows.
                      <div
                        key={group.label}
                        className="border-mkt-line-soft bg-mkt-paper-raised border-t p-2 sm:border-t-0 sm:border-l"
                      >
                        <p className="text-mkt-meta text-mkt-ink-muted px-2.5 pt-2 pb-2 uppercase">
                          {group.label}
                        </p>
                        {group.items.map((item) => (
                          <DropItemLink key={item.title} item={item} onSelect={closeDrop} />
                        ))}
                      </div>
                    ) : (
                      <div key="items" className="p-2">
                        {group.items.map((item) => (
                          <DropItemLink key={item.title} item={item} onSelect={closeDrop} />
                        ))}
                      </div>
                    ),
                  )}
                </div>
              </div>
            )}
          </AnimatePresence>
        </div>

        <div className="ml-auto flex shrink-0 items-center gap-2 lg:ml-0">
          {isAuthenticated ? (
            <ButtonLink href={dashboardHref} size="sm">
              Dashboard
            </ButtonLink>
          ) : (
            <>
              <Link
                href="/login"
                className="text-mkt-sm text-mkt-ink-soft hover:text-mkt-ink hidden px-3 font-semibold transition-colors sm:inline-flex"
              >
                Log in
              </Link>
              <ButtonLink href={DEMO_HREF} size="sm">
                {DEMO_CTA}
              </ButtonLink>
            </>
          )}
          <button
            type="button"
            className="border-mkt-line text-mkt-ink grid size-9 place-items-center rounded-sm border lg:hidden"
            aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={mobileOpen}
            aria-controls="mobile-menu"
            onClick={() => setMobileOpen((open) => !open)}
          >
            {mobileOpen ? (
              <X className="size-4" aria-hidden />
            ) : (
              <Menu className="size-4" aria-hidden />
            )}
          </button>
        </div>
      </nav>

      {mobileOpen && (
        <div
          id="mobile-menu"
          className="border-mkt-line-soft bg-mkt-paper-raised px-mkt-gutter max-h-[calc(100dvh-var(--spacing-mkt-nav))] overflow-y-auto border-t py-4 lg:hidden"
        >
          {NAV_DROPS.map(({ key, label, href, groups }) => (
            <div key={key} className="border-mkt-line-soft border-b last:border-b-0">
              <div className="flex items-center">
                <Link
                  href={href}
                  className="text-mkt-body text-mkt-ink flex-1 py-3.5 font-semibold"
                  onClick={() => setMobileOpen(false)}
                >
                  {label}
                </Link>
                <button
                  type="button"
                  className="text-mkt-ink grid size-10 place-items-center"
                  aria-label={`Open ${label} menu`}
                  aria-expanded={openAcc === key}
                  aria-controls={`acc-${key}`}
                  onClick={() => setOpenAcc((current) => (current === key ? null : key))}
                >
                  <ChevronDown
                    aria-hidden
                    className={cn(
                      'size-4 transition-transform duration-300',
                      openAcc === key && 'rotate-180',
                    )}
                  />
                </button>
              </div>
              <div id={`acc-${key}`} hidden={openAcc !== key} className="pb-2">
                {groups.map((group) => (
                  <Fragment key={group.label ?? 'items'}>
                    {group.label && (
                      <p className="text-mkt-meta text-mkt-ink-muted px-3 pt-3 pb-1 uppercase">
                        {group.label}
                      </p>
                    )}
                    {group.items.map((item) => (
                      <MobileItemLink
                        key={item.title}
                        item={item}
                        onSelect={() => {
                          setMobileOpen(false);
                          setOpenAcc(null);
                        }}
                      />
                    ))}
                  </Fragment>
                ))}
              </div>
            </div>
          ))}

          <div className="mt-4 grid gap-2">
            {NAV_LINKS.map(({ label, href }) => (
              <Link
                key={href}
                href={href}
                className="text-mkt-body text-mkt-ink py-2 font-semibold"
                onClick={() => setMobileOpen(false)}
              >
                {label}
              </Link>
            ))}
            <Link
              href={isAuthenticated ? dashboardHref : '/login'}
              className="text-mkt-body text-mkt-ink-soft py-2 font-semibold"
              onClick={() => setMobileOpen(false)}
            >
              {isAuthenticated ? 'Dashboard' : 'Log in'}
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
