'use client';

import { useEffect, useState } from 'react';
import { ChevronDown, Pause, Play, Search } from 'lucide-react';
import { m, useReducedMotion } from 'motion/react';

import { NAV_GROUPS, type NavItem } from '@/components/layout/nav-items';
import { Button } from '@/components/ui/button';
import { LogoMark } from '@/components/ui/logo-mark';
import { ICONS } from '@/lib/icons';
import { cn } from '@/lib/utils';

import { ProductPreviewPanel } from './product-preview-panels';

export const PREVIEW_STEP_MS = 1400;
export const PREVIEW_HOLD_MS = 2400;
const LAST_PHASE = 3;
type NavGroupTitle = (typeof NAV_GROUPS)[number]['title'];
type NavItemLabel = (typeof NAV_GROUPS)[number]['items'][number]['label'];

const LAYERS = [
  {
    id: 'site',
    label: 'Site Health',
    shortLabel: 'Site',
    group: 'Site Health' satisfies NavGroupTitle,
    activeItem: 'Website' satisfies NavItemLabel,
    icon: ICONS.site,
  },
  {
    id: 'content',
    label: 'Content Intelligence',
    shortLabel: 'Content',
    group: 'Content Intelligence' satisfies NavGroupTitle,
    activeItem: 'Content' satisfies NavItemLabel,
    icon: ICONS.content,
  },
  {
    id: 'demand',
    label: 'Demand Intelligence',
    shortLabel: 'Demand',
    group: 'Demand Intelligence' satisfies NavGroupTitle,
    activeItem: 'AI Visibility' satisfies NavItemLabel,
    icon: ICONS.demand,
  },
  {
    id: 'agent',
    label: 'Growth Agent',
    shortLabel: 'Agent',
    group: 'Workspace' satisfies NavGroupTitle,
    activeItem: 'Growth Agent' satisfies NavItemLabel,
    icon: ICONS.agent,
  },
] as const;

/**
 * Interactive product preview built from CiteLadder's real four-layer product
 * hierarchy and current sidebar destinations. Each layer runs a four-phase
 * demonstration, then hands the stage to the next tab. Visitors can interrupt
 * that sequence at any time by selecting a tab or pausing autoplay.
 */
export function ProductWindow() {
  const reduceMotion = useReducedMotion() ?? false;
  const [activeIndex, setActiveIndex] = useState(0);
  const [phase, setPhase] = useState(0);
  const [playing, setPlaying] = useState(true);
  const activeLayer = LAYERS[activeIndex];
  const visiblePhase = reduceMotion ? LAST_PHASE : phase;
  const playbackLabel = reduceMotion ? 'Motion reduced' : playing ? 'Pause' : 'Play';
  const playbackAriaLabel = reduceMotion ? playbackLabel : `${playbackLabel} product preview`;

  useEffect(() => {
    if (!playing || reduceMotion) return;
    const delay = phase === LAST_PHASE ? PREVIEW_HOLD_MS : PREVIEW_STEP_MS;
    const timer = window.setTimeout(() => {
      if (phase < LAST_PHASE) {
        setPhase((current) => current + 1);
        return;
      }
      setActiveIndex((current) => (current + 1) % LAYERS.length);
      setPhase(0);
    }, delay);
    return () => window.clearTimeout(timer);
  }, [activeIndex, phase, playing, reduceMotion]);

  const selectLayer = (index: number) => {
    setActiveIndex(index);
    setPhase(0);
  };

  return (
    <div
      data-testid="product-window"
      className="app-type-scale border-border-strong bg-panel shadow-elevated mx-auto w-full max-w-[1240px] overflow-hidden rounded-xl border"
    >
      <div
        role="tablist"
        aria-label="CiteLadder intelligence layers"
        className="border-border-subtle bg-panel grid grid-cols-2 border-b md:grid-cols-4"
      >
        {LAYERS.map((layer, index) => {
          const Icon = layer.icon;
          const selected = index === activeIndex;
          return (
            <button
              key={layer.id}
              id={`product-preview-tab-${layer.id}`}
              type="button"
              role="tab"
              aria-label={layer.label}
              aria-selected={selected}
              aria-controls="product-preview-panel"
              onClick={() => selectLayer(index)}
              className={cn(
                'focus-ring relative flex min-h-14 items-center justify-center gap-2 px-3 text-sm font-medium transition-colors md:min-h-16',
                index > 0 && 'border-border-subtle border-l',
                selected
                  ? 'text-foreground bg-background-alt/60'
                  : 'text-muted hover:text-foreground',
              )}
            >
              <Icon className={cn('size-3.5', selected && 'text-accent-text')} strokeWidth={2} />
              <span className="sm:hidden">{layer.shortLabel}</span>
              <span className="hidden sm:inline">{layer.label}</span>
              {selected ? (
                <span className="bg-border-subtle absolute inset-x-0 bottom-0 h-0.5 overflow-hidden">
                  <m.span
                    key={`${layer.id}-${phase}`}
                    className="bg-accent block h-full origin-left"
                    initial={{ scaleX: Math.max(phase / (LAST_PHASE + 1), 0.04) }}
                    animate={{ scaleX: (phase + 1) / (LAST_PHASE + 1) }}
                    transition={
                      reduceMotion || !playing
                        ? { duration: 0 }
                        : { duration: PREVIEW_STEP_MS / 1000, ease: 'linear' }
                    }
                  />
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      <div className="bg-background grid min-h-[690px] lg:grid-cols-[220px_minmax(0,1fr)]">
        <PreviewSidebar activeItem={activeLayer.activeItem} />

        <div className="flex min-w-0 flex-col">
          <header className="border-border-subtle bg-panel flex h-13 shrink-0 items-center gap-3 border-b px-3 sm:px-4">
            <div className="flex items-center gap-2 lg:hidden">
              <LogoMark size={16} />
              <span className="font-display text-foreground hidden text-sm font-bold sm:inline">
                CiteLadder
              </span>
            </div>
            <div className="border-border-strong bg-background text-muted flex h-8 max-w-80 min-w-0 flex-1 items-center gap-2 rounded-md border px-3 text-[13px] shadow-xs lg:mx-auto">
              <Search className="size-3.5 shrink-0" strokeWidth={2} />
              <span className="truncate">Search pages, evidence, prompts…</span>
              <span className="border-border bg-panel ml-auto hidden rounded-xs border px-1.5 py-0.5 text-[10px] sm:inline">
                ⌘ K
              </span>
            </div>
            <span className="bg-neutral-bg text-secondary hidden rounded-full px-2.5 py-1 text-[11px] font-medium sm:inline-flex">
              Illustrative workspace
            </span>
            <Button
              variant="secondary"
              size="sm"
              disabled={reduceMotion}
              onClick={() => setPlaying((current) => !current)}
              aria-label={playbackAriaLabel}
              className="h-11 shrink-0 px-2.5 sm:h-[var(--control-height-sm)]"
            >
              {playing ? (
                <Pause className="size-3" aria-hidden />
              ) : (
                <Play className="size-3" aria-hidden />
              )}
              <span className="hidden sm:inline">{playbackLabel}</span>
            </Button>
          </header>

          <MobileSubnav groupTitle={activeLayer.group} activeItem={activeLayer.activeItem} />

          <div
            id="product-preview-panel"
            role="tabpanel"
            aria-labelledby={`product-preview-tab-${activeLayer.id}`}
            className="min-h-0 flex-1 overflow-hidden"
          >
            <ProductPreviewPanel
              layer={activeLayer.id}
              phase={visiblePhase}
              reduceMotion={reduceMotion}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function PreviewSidebar({ activeItem }: Readonly<{ activeItem: NavItemLabel }>) {
  return (
    <aside className="border-border-subtle bg-sidebar hidden border-r lg:flex lg:flex-col">
      <div className="border-border-subtle flex h-13 items-center gap-2.5 border-b px-4">
        <LogoMark size={16} />
        <span className="font-display text-foreground text-sm font-bold">CiteLadder</span>
      </div>
      <div className="border-border-subtle border-b p-2">
        <div className="hover:bg-background-alt flex items-center gap-2 rounded-sm px-2 py-1.5">
          <span className="bg-foreground text-background flex size-7 items-center justify-center rounded-md text-[10px] font-semibold">
            AC
          </span>
          <span className="text-foreground min-w-0 flex-1 truncate text-[13px] font-medium">
            Acme Corp
          </span>
          <ChevronDown className="text-muted size-3.5" strokeWidth={2} />
        </div>
      </div>
      <nav
        className="sidebar-scroll min-h-0 flex-1 overflow-y-auto p-2"
        aria-label="Product preview navigation"
      >
        <div className="grid gap-2.5">
          {NAV_GROUPS.map((group) => (
            <div key={group.title}>
              <p className="text-subtle px-2 pb-1 text-[11px] font-semibold">{group.title}</p>
              <div className="grid gap-0.5">
                {previewItems(group.title).map((item) => {
                  const Icon = item.icon;
                  const active = item.label === activeItem;
                  return (
                    <div
                      key={item.label}
                      className={cn(
                        'relative flex h-7 items-center gap-2 rounded-sm px-2 text-[13px] font-medium transition-[background-color,color] duration-200',
                        active ? 'bg-accent-soft text-accent-hover' : 'text-secondary',
                      )}
                    >
                      {active ? (
                        <span className="bg-accent absolute inset-y-1 left-0 w-1 rounded-r-sm" />
                      ) : null}
                      <Icon className="size-3.5" strokeWidth={2} />
                      <span>{item.label}</span>
                      {item.count ? (
                        <span className="bg-neutral-bg text-secondary ml-auto rounded-full px-1.5 text-[10px]">
                          {item.count}
                        </span>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </nav>
      <div className="border-border-subtle border-t p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="text-subtle text-[11px]">Preview run</span>
          <span className="text-success-text text-[11px] font-medium">Evidence linked</span>
        </div>
      </div>
    </aside>
  );
}

function MobileSubnav({
  groupTitle,
  activeItem,
}: Readonly<{ groupTitle: NavGroupTitle; activeItem: NavItemLabel }>) {
  const items = previewItems(groupTitle);
  return (
    <div className="border-border-subtle bg-panel flex gap-1 overflow-x-auto border-b px-3 py-2 lg:hidden">
      {items.map((item) => (
        <span
          key={item.label}
          className={cn(
            'shrink-0 rounded-sm px-2.5 py-1.5 text-xs font-medium',
            item.label === activeItem ? 'bg-accent-soft text-accent-text' : 'text-muted',
          )}
        >
          {item.label}
        </span>
      ))}
    </div>
  );
}

function previewItems(groupTitle: NavGroupTitle): readonly NavItem[] {
  const group = NAV_GROUPS.find((candidate) => candidate.title === groupTitle);
  if (!group) return [];
  return group.items.filter((item) => item.label !== 'Search Demand');
}
