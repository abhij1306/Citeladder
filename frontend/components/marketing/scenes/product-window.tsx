import { ICONS } from '@/lib/icons';
import { cn } from '@/lib/utils';

import { Meta } from '../primitives/label';
import { ExampleDataNote, WallpaperPanel } from './wallpaper-panel';

/**
 * The product canvas: the real workspace shell on the wallpaper. The sidebar
 * mirrors the app's actual Analyze / Improve groups and their real labels
 * (components/layout/nav-items.ts) rather than inventing a friendlier
 * information architecture for the marketing site — a visitor who books a
 * demo should recognise the screen they were shown.
 *
 * The figures are illustrative, so the whole canvas is aria-hidden and the
 * "Example data" mark stays visible.
 */
// Real labels AND real glyphs, straight off the canonical icon map, so the
// scene is the product rather than a drawing of it.
const SIDEBAR = [
  {
    group: 'Analyze',
    items: [
      { label: 'Visibility', Icon: ICONS.visibility },
      { label: 'Answers', Icon: ICONS.analytics },
      { label: 'Traffic', Icon: ICONS.traffic },
      { label: 'Commerce', Icon: ICONS.products },
    ],
  },
  {
    group: 'Improve',
    items: [
      { label: 'Content', Icon: ICONS.content },
      { label: 'Site health', Icon: ICONS.siteHealth },
      { label: 'Opportunities', Icon: ICONS.opportunities },
    ],
  },
] as const;

const METRICS: readonly { label: string; value: string; delta?: string }[] = [
  { label: 'Visibility index', value: '72.4', delta: '+4.8' },
  { label: 'Share of voice', value: '18.6', delta: '+2.1' },
  { label: 'Answers observed', value: '1,248' },
  { label: 'Citations traced', value: '3,091' },
];

const RANKING = [
  ['ChatGPT', '81'],
  ['Gemini', '76'],
  ['Claude', '68'],
] as const;

const PANEL = 'rounded-mkt-sm bg-mkt-paper-raised shadow-card p-4';

export function ProductWindow() {
  return (
    <WallpaperPanel className="p-3 sm:p-6 lg:p-8">
      <div className="mb-3 flex items-center justify-between gap-3">
        <Meta as="p" className="text-mkt-ink-muted">
          Workspace / market overview
        </Meta>
        <ExampleDataNote />
      </div>

      <div aria-hidden className="grid lg:grid-cols-[13.75rem_minmax(0,1fr)]">
        <aside className="bg-mkt-surface hidden rounded-lg p-5 shadow-card lg:block lg:rounded-r-none">
          {SIDEBAR.map(({ group, items }) => (
            <div key={group} className="mb-5 last:mb-0">
              <Meta as="p" className="text-mkt-ink-muted mb-2 px-2">
                {group}
              </Meta>
              {items.map(({ label, Icon }, index) => (
                <div
                  key={label}
                  className={cn(
                    'text-mkt-sm flex items-center gap-2.5 rounded-sm px-2.5 py-2',
                    group === 'Analyze' && index === 0
                      ? 'bg-mkt-proof-soft text-mkt-proof font-semibold'
                      : 'text-mkt-ink-muted',
                  )}
                >
                  <Icon className="size-3.5 shrink-0" strokeWidth={1.75} />
                  {label}
                </div>
              ))}
            </div>
          ))}
        </aside>

        <div className="bg-mkt-surface rounded-lg p-4 shadow-card sm:p-5 lg:rounded-l-none">
          <div className="mb-4 flex items-center justify-between gap-3">
            <p className="font-mkt-display text-mkt-ink text-heading-sm font-semibold">
              Market overview
            </p>
            <Meta className="border-mkt-line rounded-sm border px-2 py-1">Apr 01 — Jun 30</Meta>
          </div>

          <div className="border-mkt-line-soft rounded-mkt-sm grid grid-cols-2 border md:grid-cols-4">
            {METRICS.map((metric, index) => (
              <div
                key={metric.label}
                className={cn(
                  'border-mkt-line-soft p-3 sm:p-4',
                  // Two columns below md, four above: the middle divider only
                  // exists once the strip is a single row.
                  index % 2 === 0 && 'border-r',
                  index === 1 && 'md:border-r',
                  index < 2 && 'border-b md:border-b-0',
                )}
              >
                <Meta as="p" className="text-mkt-ink-muted">
                  {metric.label}
                </Meta>
                <b className="text-mkt-ink mt-2 block font-mono text-xl leading-none font-medium tabular-nums">
                  {metric.value}
                  {metric.delta && (
                    <small className="text-mkt-evidence-text text-mkt-meta ml-1.5 font-mono font-medium tabular-nums">
                      {metric.delta}
                    </small>
                  )}
                </b>
              </div>
            ))}
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_13.75rem]">
            <div className={PANEL}>
              <div className="text-mkt-ink-muted text-mkt-sm flex justify-between">
                <span>Category visibility</span>
                <Meta>12 weeks</Meta>
              </div>
              <svg
                viewBox="0 0 620 230"
                preserveAspectRatio="none"
                className="mt-3 h-36 w-full sm:h-44"
              >
                <path d="M0 45H620M0 90H620M0 135H620M0 180H620" className="stroke-mkt-line" />
                <path
                  className="mkt-chart-line stroke-mkt-proof animate-mkt-draw"
                  pathLength={440}
                  d="M0 186 C55 170 72 178 120 146 S185 154 235 119 S310 137 360 88 S430 110 485 65 S555 73 620 35"
                />
                <path
                  className="mkt-chart-line stroke-mkt-evidence animate-mkt-draw"
                  pathLength={440}
                  style={{ animationDelay: '0.45s' }}
                  d="M0 202 C60 190 98 158 150 171 S238 142 290 151 S365 119 415 127 S515 99 620 88"
                />
              </svg>
            </div>

            <div className={PANEL}>
              <div className="text-mkt-ink-muted text-mkt-sm mb-1">Provider view</div>
              {RANKING.map(([engine, score], index) => (
                <div
                  key={engine}
                  className="border-mkt-line-soft text-mkt-ink-soft text-mkt-sm grid grid-cols-[1.125rem_1fr_auto] items-center gap-2 border-b py-2 last:border-b-0"
                >
                  <b className="bg-mkt-proof-soft text-mkt-proof text-mkt-meta grid size-4.5 place-items-center rounded-sm font-mono tabular-nums">
                    {index + 1}
                  </b>
                  <span>{engine}</span>
                  <strong className="text-mkt-ink font-mono font-medium tabular-nums">
                    {score}
                  </strong>
                </div>
              ))}
            </div>
          </div>

          <div className="border-mkt-evidence-line bg-mkt-evidence-soft mt-3 flex flex-wrap justify-between gap-x-6 gap-y-1.5 rounded-sm border px-4 py-2.5">
            <Meta className="text-mkt-evidence-text">Raw artifacts preserved / 1,248</Meta>
            <Meta className="text-mkt-evidence-text">Analyzer / visibility-v4.2</Meta>
            <Meta className="text-mkt-evidence-text">Reproducible / yes</Meta>
          </div>
        </div>
      </div>
    </WallpaperPanel>
  );
}
