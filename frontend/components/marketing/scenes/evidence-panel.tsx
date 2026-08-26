import { Download, FileSpreadsheet, ShoppingBag } from 'lucide-react';

import type { SolutionScene } from '@/lib/marketing-content/solutions';

import { Badge } from '@/components/ui/badge';
import { Meta } from '../primitives/label';
import { Panel, WallpaperPanel } from './wallpaper-panel';

/**
 * Product snapshot panels, one per audience segment.
 * Displays clear, structured, and realistic evidence metrics for each segment.
 */
function Bar({ width, own = false }: Readonly<{ width: number; own?: boolean }>) {
  return (
    <span className="bg-background-alt block h-2 flex-1 overflow-hidden rounded-full">
      {/* Scaled rather than sized: animating `width` relayouts the row on every
          frame, while `transform` stays on the compositor. */}
      <span
        style={{ transform: `scaleX(${width / 100})` }}
        className={`block h-full w-full origin-left rounded-full transition-transform duration-300 ${
          own ? 'bg-accent' : 'bg-border'
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
        <div className="grid gap-5">
          {[
            { name: 'Acme Corp (Client)', share: 68, mentions: '84 mentions', own: true },
            { name: 'Vortex AI (Rival)', share: 42, mentions: '52 mentions', own: false },
            { name: 'Apex Labs (Rival)', share: 24, mentions: '30 mentions', own: false },
          ].map(({ name, share, mentions, own }) => (
            <div key={name} className="flex flex-col gap-2">
              <div className="flex items-center justify-between text-sm">
                <span
                  className={`font-medium ${own ? 'text-foreground font-medium' : 'text-muted'}`}
                >
                  {name}
                </span>
                <span className="text-muted font-mono text-xs">
                  {share}% SOV · {mentions}
                </span>
              </div>
              <Bar width={share} own={own} />
            </div>
          ))}
        </div>
        <div className="border-border-subtle mt-5 flex flex-wrap items-center justify-between gap-3 border-t pt-5">
          <div className="flex flex-wrap gap-3">
            <span className="border-border-subtle bg-background-alt text-muted inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium">
              <Download aria-hidden strokeWidth={2} className="size-4" />
              Mentions (CSV)
            </span>
            <span className="border-border-subtle bg-background-alt text-muted inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium">
              <FileSpreadsheet aria-hidden strokeWidth={2} className="size-4" />
              Evidence (Markdown)
            </span>
          </div>
          <Badge variant="status" value="info">
            4 Engines Audited
          </Badge>
        </div>
      </>
    ),
  },
  health: {
    label: 'Site health — Web Fundamentals & AEO',
    body: (
      <>
        <div className="grid gap-5">
          {[
            { name: 'Web Fundamentals', value: 88, status: 'Optimal' },
            { name: 'AEO Readiness', value: 74, status: 'Good' },
            { name: 'Schema Validation', value: 92, status: 'Validated' },
          ].map(({ name, value, status }) => (
            <div key={name} className="flex flex-col gap-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-foreground font-medium">{name}</span>
                <div className="flex items-center gap-3">
                  <span className="text-muted text-xs">{status}</span>
                  <span className="text-foreground font-mono font-medium tabular-nums">
                    {value}/100
                  </span>
                </div>
              </div>
              <Bar width={value} own={value >= 80} />
            </div>
          ))}
        </div>
        <div className="border-border-subtle mt-5 flex flex-wrap gap-3 border-t pt-5">
          <Badge variant="status" value="success">
            Search Console Synced
          </Badge>
          <Badge variant="status" value="success">
            GA4 Connected
          </Badge>
          <Badge>33 Rules Checked</Badge>
        </div>
      </>
    ),
  },
  sample: {
    label: 'Sample crawl — seeded and capped',
    body: (
      <>
        <div className="grid gap-4">
          {[
            { label: 'Pages Sampled', val: '25 / 25 Seeded URLs' },
            { label: 'Prompts Tested', val: '50 Target Queries' },
            { label: 'AI Recommendation Rate', val: '78% Positive Mention' },
            { label: 'BYOK Provider Cost', val: '$0.14 Total API Cost' },
          ].map(({ label, val }) => (
            <div
              key={label}
              className="border-border-subtle flex items-center justify-between border-b pb-3 text-sm last:border-b-0 last:pb-0"
            >
              <span className="text-muted">{label}</span>
              <span className="text-foreground font-mono font-medium">{val}</span>
            </div>
          ))}
        </div>
        <div className="border-border-subtle mt-5 flex flex-wrap gap-3 border-t pt-5">
          <Badge variant="status" value="info">
            Raw Run Persisted
          </Badge>
          <Badge>Zero Lock-In</Badge>
        </div>
      </>
    ),
  },
  commerce: {
    label: 'Ecommerce — product AI visibility',
    body: (
      <>
        <div className="border-border-subtle bg-background-alt rounded-md border p-4">
          <div className="flex items-center justify-between text-sm">
            <span className="text-foreground flex items-center gap-3 font-medium">
              <ShoppingBag className="text-accent-text size-4" aria-hidden />
              Acoustic Pro ANC Headphones
            </span>
            <Badge variant="status" value="success">
              100% Price Match
            </Badge>
          </div>
          <div className="border-border-subtle mt-4 grid grid-cols-2 gap-3 border-t pt-4 text-sm">
            <div>
              <span className="text-muted block text-xs">Quoted Price</span>
              <span className="text-foreground font-mono font-medium">$299.00</span>
            </div>
            <div>
              <span className="text-muted block text-xs">Engine Rank</span>
              <span className="text-accent-text font-medium">#1 Recommended</span>
            </div>
          </div>
        </div>
        <div className="text-muted mt-5 flex items-center justify-between text-sm">
          <span>Competitor Co-Placement:</span>
          <span className="text-foreground font-medium">Sony WH-1000XM5</span>
        </div>
        <div className="border-border-subtle mt-5 flex flex-wrap gap-3 border-t pt-5">
          <Badge variant="status" value="info">
            Catalog Evidence Synced
          </Badge>
          <Badge variant="status" value="success">
            64% SKU Share of Voice
          </Badge>
        </div>
      </>
    ),
  },
  citations: {
    label: 'Citation ownership — per prompt',
    body: (
      <>
        <div className="bg-background-alt border-border-subtle text-foreground mb-5 rounded-md border p-4 text-sm font-medium">
          &quot;What are the top enterprise AI search platforms?&quot;
        </div>
        <div className="grid gap-4">
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
            <div key={label} className="flex flex-col gap-2">
              <div className="flex items-center justify-between text-sm">
                <span
                  className={`font-medium ${own ? 'text-foreground font-medium' : 'text-muted'}`}
                >
                  {label}
                </span>
                <span className="text-muted font-mono text-xs">{engines}</span>
              </div>
              <Bar width={share} own={own} />
            </div>
          ))}
        </div>
        <div className="border-border-subtle mt-5 flex flex-wrap gap-3 border-t pt-5">
          <Badge variant="status" value="info">
            Query Fanout Tracked
          </Badge>
          <Badge>Coverage Report Ready</Badge>
        </div>
      </>
    ),
  },
};

export function SolutionEvidencePanel({ scene }: Readonly<{ scene: SolutionScene }>) {
  const { label, body } = PANELS[scene];
  return (
    <WallpaperPanel className="p-5 sm:p-8">
      <Meta as="p" className="text-muted mb-4 font-medium">
        {label}
      </Meta>
      <Panel className="p-5">
        {/* The illustrative rows stay hidden from assistive technology so they
            are never announced as persisted customer evidence. */}
        <div aria-hidden>{body}</div>
      </Panel>
    </WallpaperPanel>
  );
}
