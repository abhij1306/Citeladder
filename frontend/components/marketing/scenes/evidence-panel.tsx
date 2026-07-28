import { Download } from 'lucide-react';

import type { SolutionScene } from '@/lib/marketing-content/solutions';

import { Badge } from '../primitives/badge';
import { Meta } from '../primitives/label';
import { ExampleDataNote, Panel, WallpaperPanel } from './wallpaper-panel';

/**
 * Four small product panels, one per audience segment. They show the SHAPE of
 * a surface — rows, bars, chips — with no brand names, no client, and no
 * verdicts. Building them from one component (rather than four bespoke CSS
 * illustrations, which is what the previous system accumulated) is what keeps
 * a new segment from needing new stylesheet rules.
 */
const SHARE_ROWS = [72, 54, 44, 31] as const;
const GAUGES = [
  { name: 'Technical', value: 82 },
  { name: 'AEO', value: 64 },
] as const;

function Bar({ width, own = false }: Readonly<{ width: number; own?: boolean }>) {
  return (
    <span className="bg-mkt-surface-sunk block h-2 flex-1 overflow-hidden rounded-full">
      <span
        style={{ width: `${width}%` }}
        className={`block h-full rounded-full ${own ? 'bg-mkt-proof' : 'bg-mkt-line-strong'}`}
      />
    </span>
  );
}

function Placeholder({ width }: Readonly<{ width: string }>) {
  return <span style={{ width }} className="bg-mkt-surface-sunk block h-2 rounded-full" />;
}

const PANELS: Record<SolutionScene, { label: string; body: React.ReactNode }> = {
  share: {
    label: 'Client report — share of answers',
    body: (
      <>
        <div className="grid gap-3">
          {SHARE_ROWS.map((width, index) => (
            <div key={width} className="flex items-center gap-3">
              <Placeholder width={index === 0 ? '32%' : '24%'} />
              <Bar width={width} own={index === 0} />
            </div>
          ))}
        </div>
        <div className="mt-5 flex flex-wrap gap-2">
          {['Mentions (CSV)', 'Evidence (Markdown)'].map((label) => (
            <span
              key={label}
              className="border-mkt-line bg-mkt-paper-raised text-mkt-ink-soft text-mkt-sm inline-flex items-center gap-2 rounded-sm border px-2.5 py-1.5"
            >
              <Download aria-hidden strokeWidth={2} className="size-3.5" />
              {label}
            </span>
          ))}
        </div>
      </>
    ),
  },
  health: {
    label: 'Site health — technical & AEO',
    body: (
      <>
        <div className="grid gap-4">
          {GAUGES.map(({ name, value }) => (
            <div key={name} className="flex items-center gap-3">
              <span className="text-mkt-sm text-mkt-ink-soft w-20 shrink-0">{name}</span>
              <Bar width={value} own={name === 'Technical'} />
              <span className="text-mkt-sm text-mkt-ink w-6 text-right font-mono font-medium tabular-nums">
                {value}
              </span>
            </div>
          ))}
        </div>
        <div className="mt-5 flex flex-wrap gap-2">
          <Badge tone="warn">12 to review</Badge>
          <Badge tone="good">Reproducible</Badge>
        </div>
      </>
    ),
  },
  sample: {
    label: 'Sample crawl — seeded and capped',
    body: (
      <div className="grid gap-3">
        {['Pages sampled', 'Prompts run', 'Answers persisted'].map((row, index) => (
          <div
            key={row}
            className="border-mkt-line-soft flex items-center justify-between gap-4 border-b pb-3 last:border-b-0 last:pb-0"
          >
            <span className="text-mkt-sm text-mkt-ink-soft">{row}</span>
            <Placeholder width={`${[64, 48, 56][index]}px`} />
          </div>
        ))}
      </div>
    ),
  },
  citations: {
    label: 'Citation ownership — per prompt',
    body: (
      <div className="grid gap-3">
        {[
          { tone: 'proof' as const, label: 'Owned' },
          { tone: 'neutral' as const, label: 'Third party' },
          { tone: 'warn' as const, label: 'Competitor' },
        ].map(({ tone, label }, index) => (
          <div key={label} className="flex items-center gap-3">
            <Badge tone={tone}>{label}</Badge>
            <Bar width={[58, 34, 22][index]} own={tone === 'proof'} />
          </div>
        ))}
      </div>
    ),
  },
};

export function SolutionEvidencePanel({ scene }: Readonly<{ scene: SolutionScene }>) {
  const { label, body } = PANELS[scene];
  return (
    <WallpaperPanel className="p-4 sm:p-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <Meta as="p" className="text-mkt-ink-muted">
          {label}
        </Meta>
        <ExampleDataNote />
      </div>
      <Panel className="p-5">
        <div aria-hidden>{body}</div>
      </Panel>
    </WallpaperPanel>
  );
}
