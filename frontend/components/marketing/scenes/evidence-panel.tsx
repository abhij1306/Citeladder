import { Download, FileSpreadsheet, ShoppingBag } from 'lucide-react';

import type { SolutionScene } from '@/lib/marketing-content/solutions';

import { Badge } from '../primitives/badge';
import { Meta } from '../primitives/label';
import { ExampleDataNote, Panel, WallpaperPanel } from './wallpaper-panel';

/**
 * Product snapshot panels, one per audience segment.
 * Displays clear, structured, and realistic evidence metrics for each segment.
 */
function Bar({ width, own = false }: Readonly<{ width: number; own?: boolean }>) {
  return (
    <span className="bg-mkt-surface-sunk block h-2 flex-1 overflow-hidden rounded-full">
      <span
        style={{ width: `${width}%` }}
        className={`block h-full rounded-full transition-all duration-300 ${
          own ? 'bg-mkt-proof' : 'bg-mkt-line-strong'
        }`}
      />
    </span>
  );
}

const PANELS: Record<SolutionScene, { label: string; body: React.ReactNode }> = {
  share: {
    label: 'Client report — share of answers',
    body: (
      <>
        <div className="grid gap-4">
          {[
            { name: 'Acme Corp (Client)', share: 68, mentions: '84 mentions', own: true },
            { name: 'Vortex AI (Rival)', share: 42, mentions: '52 mentions', own: false },
            { name: 'Apex Labs (Rival)', share: 24, mentions: '30 mentions', own: false },
          ].map(({ name, share, mentions, own }) => (
            <div key={name} className="flex flex-col gap-1.5">
              <div className="text-mkt-sm flex items-center justify-between">
                <span
                  className={`font-medium ${own ? 'text-mkt-ink font-semibold' : 'text-mkt-ink-soft'}`}
                >
                  {name}
                </span>
                <span className="text-mkt-meta text-mkt-ink-muted font-mono">
                  {share}% SOV · {mentions}
                </span>
              </div>
              <Bar width={share} own={own} />
            </div>
          ))}
        </div>
        <div className="border-mkt-line-soft mt-5 flex flex-wrap items-center justify-between gap-2 border-t pt-4">
          <div className="flex flex-wrap gap-2">
            <span className="border-mkt-line bg-mkt-paper-raised text-mkt-ink-soft text-mkt-sm inline-flex items-center gap-1.5 rounded-sm border px-3 py-1 font-medium">
              <Download aria-hidden strokeWidth={2} className="size-4" />
              Mentions (CSV)
            </span>
            <span className="border-mkt-line bg-mkt-paper-raised text-mkt-ink-soft text-mkt-sm inline-flex items-center gap-1.5 rounded-sm border px-3 py-1 font-medium">
              <FileSpreadsheet aria-hidden strokeWidth={2} className="size-4" />
              Evidence (Markdown)
            </span>
          </div>
          <Badge tone="proof">4 Engines Audited</Badge>
        </div>
      </>
    ),
  },
  health: {
    label: 'Site health — technical & AEO',
    body: (
      <>
        <div className="grid gap-4">
          {[
            { name: 'Technical Health', value: 88, status: 'Optimal' },
            { name: 'AEO Readiness', value: 74, status: 'Good' },
            { name: 'Schema Validation', value: 92, status: 'Validated' },
          ].map(({ name, value, status }) => (
            <div key={name} className="flex flex-col gap-1.5">
              <div className="text-mkt-sm flex items-center justify-between">
                <span className="text-mkt-ink font-medium">{name}</span>
                <div className="flex items-center gap-2">
                  <span className="text-mkt-meta text-mkt-ink-muted">{status}</span>
                  <span className="text-mkt-ink font-mono font-semibold tabular-nums">
                    {value}/100
                  </span>
                </div>
              </div>
              <Bar width={value} own={value >= 80} />
            </div>
          ))}
        </div>
        <div className="border-mkt-line-soft mt-5 flex flex-wrap gap-2 border-t pt-4">
          <Badge tone="good">Search Console Synced</Badge>
          <Badge tone="good">GA4 Connected</Badge>
          <Badge tone="neutral">33 Rules Checked</Badge>
        </div>
      </>
    ),
  },
  sample: {
    label: 'Sample crawl — seeded and capped',
    body: (
      <>
        <div className="grid gap-3">
          {[
            { label: 'Pages Sampled', val: '25 / 25 Seeded URLs' },
            { label: 'Prompts Tested', val: '50 Target Queries' },
            { label: 'AI Recommendation Rate', val: '78% Positive Mention' },
            { label: 'BYOK Provider Cost', val: '$0.14 Total API Cost' },
          ].map(({ label, val }) => (
            <div
              key={label}
              className="border-mkt-line-soft text-mkt-sm flex items-center justify-between border-b pb-2 last:border-b-0 last:pb-0"
            >
              <span className="text-mkt-ink-soft">{label}</span>
              <span className="text-mkt-ink font-mono font-medium">{val}</span>
            </div>
          ))}
        </div>
        <div className="border-mkt-line-soft mt-4 flex flex-wrap gap-2 border-t pt-4">
          <Badge tone="proof">Raw Run Persisted</Badge>
          <Badge tone="neutral">Zero Lock-In</Badge>
        </div>
      </>
    ),
  },
  commerce: {
    label: 'Ecommerce — product AI visibility',
    body: (
      <>
        <div className="rounded-mkt-sm border-mkt-line-soft bg-mkt-paper-raised border p-3">
          <div className="text-mkt-sm flex items-center justify-between">
            <span className="text-mkt-ink flex items-center gap-2 font-semibold">
              <ShoppingBag className="text-mkt-proof size-4" aria-hidden />
              Acoustic Pro ANC Headphones
            </span>
            <Badge tone="good">100% Price Match</Badge>
          </div>
          <div className="border-mkt-line-soft text-mkt-sm mt-3 grid grid-cols-2 gap-2 border-t pt-3">
            <div>
              <span className="text-mkt-meta text-mkt-ink-muted block">Quoted Price</span>
              <span className="text-mkt-ink font-mono font-semibold">$299.00</span>
            </div>
            <div>
              <span className="text-mkt-meta text-mkt-ink-muted block">Engine Rank</span>
              <span className="text-mkt-proof font-medium">#1 Recommended</span>
            </div>
          </div>
        </div>
        <div className="text-mkt-sm text-mkt-ink-soft mt-4 flex items-center justify-between">
          <span>Competitor Co-Placement:</span>
          <span className="text-mkt-ink font-medium">Sony WH-1000XM5</span>
        </div>
        <div className="border-mkt-line-soft mt-4 flex flex-wrap gap-2 border-t pt-4">
          <Badge tone="proof">Shopify Catalog Synced</Badge>
          <Badge tone="good">64% SKU Share of Voice</Badge>
        </div>
      </>
    ),
  },
  citations: {
    label: 'Citation ownership — per prompt',
    body: (
      <>
        <div className="rounded-mkt-sm bg-mkt-surface-sunk border-mkt-line-soft text-mkt-sm text-mkt-ink mb-4 border p-3 font-medium">
          &quot;What are the top enterprise AI search platforms?&quot;
        </div>
        <div className="grid gap-3">
          {[
            {
              label: 'Owned Domain (Press Release)',
              share: 58,
              engines: 'Cited in 4/5 engines',
              own: true,
            },
            {
              label: 'TechCrunch (Earned Media)',
              share: 34,
              engines: 'Cited in 3/5 engines',
              own: false,
            },
            {
              label: 'Competitor Domain',
              share: 18,
              engines: 'Cited in 1/5 engines',
              own: false,
            },
          ].map(({ label, share, engines, own }) => (
            <div key={label} className="flex flex-col gap-1">
              <div className="text-mkt-sm flex items-center justify-between">
                <span
                  className={`font-medium ${own ? 'text-mkt-ink font-semibold' : 'text-mkt-ink-soft'}`}
                >
                  {label}
                </span>
                <span className="text-mkt-meta text-mkt-ink-muted font-mono">{engines}</span>
              </div>
              <Bar width={share} own={own} />
            </div>
          ))}
        </div>
        <div className="border-mkt-line-soft mt-4 flex flex-wrap gap-2 border-t pt-4">
          <Badge tone="proof">Query Fanout Tracked</Badge>
          <Badge tone="neutral">Coverage Report Ready</Badge>
        </div>
      </>
    ),
  },
};

export function SolutionEvidencePanel({ scene }: Readonly<{ scene: SolutionScene }>) {
  const { label, body } = PANELS[scene];
  return (
    <WallpaperPanel className="p-4 sm:p-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <Meta as="p" className="text-mkt-ink-muted font-medium">
          {label}
        </Meta>
        <ExampleDataNote />
      </div>
      <Panel className="p-5">
        {/* Every figure below is fabricated. `ExampleDataNote` above stays
            readable — it is the honesty mark — but the rows themselves are
            hidden, so a screen reader is not read a table of invented metrics
            as if it were page content. */}
        <div aria-hidden>{body}</div>
      </Panel>
    </WallpaperPanel>
  );
}
