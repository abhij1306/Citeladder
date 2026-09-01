import { BarChart3, Gauge, Link2, Search } from 'lucide-react';

import { cn } from '@/lib/utils';

import {
  MetricStrip,
  PreviewBadge,
  PreviewButton,
  PRIMARY_SURFACE,
  SUPPORTING_SURFACE,
  ScreenHeader,
  type PreviewProps,
} from './shared';

const DEMAND_VIEWS = ['Trends', 'Mentions & Citations', 'Query Fanout'] as const;

export function DemandPreview({ phase }: PreviewProps) {
  const activeView = DEMAND_VIEWS[Math.min(phase, DEMAND_VIEWS.length - 1)] ?? DEMAND_VIEWS[0];

  return (
    <div data-preview-layer="demand" className="p-4 sm:p-5">
      <ScreenHeader
        icon={<BarChart3 className="size-4" aria-hidden />}
        title="AI Visibility"
        description="Inspect mentions, citations, competitors, and query fanout from completed audits."
        action={
          <PreviewButton>
            <Gauge className="size-3" aria-hidden />
            Run audit
          </PreviewButton>
        }
      />

      <section className={cn(PRIMARY_SURFACE, 'mt-4 min-h-[510px] overflow-hidden')}>
        <div className="border-border flex flex-wrap items-center justify-between gap-3 border-b px-4 pt-3">
          <div className="flex gap-5 overflow-x-auto" aria-label="AI Visibility views">
            {DEMAND_VIEWS.map((view) => (
              <span
                key={view}
                aria-current={view === activeView ? 'page' : undefined}
                className={cn(
                  'relative shrink-0 pb-3 text-sm font-medium',
                  view === activeView ? 'text-foreground' : 'text-muted',
                )}
              >
                {view}
                {view === activeView ? (
                  <span className="bg-accent absolute inset-x-0 bottom-0 h-0.5" />
                ) : null}
              </span>
            ))}
          </div>
          <div className="mb-3 flex items-center gap-2">
            <PreviewBadge>All engines</PreviewBadge>
            <PreviewBadge tone="info">Latest run</PreviewBadge>
          </div>
        </div>

        {activeView === 'Trends' ? <VisibilityTrendsPreview /> : null}
        {activeView === 'Mentions & Citations' ? <VisibilityContentPreview /> : null}
        {activeView === 'Query Fanout' ? <VisibilityFanoutPreview /> : null}
      </section>
    </div>
  );
}

function VisibilityTrendsPreview() {
  return (
    <div className="p-4">
      <MetricStrip
        items={[
          { label: 'Visibility score', value: '62%', detail: '+8.4 pts' },
          { label: 'Share of voice', value: '47%', detail: '+5.1 pts' },
          { label: 'Brand mentions', value: '78%', detail: '39 of 50' },
          { label: 'Owned citations', value: '31%', detail: '18 sources' },
        ]}
      />
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <VisibilityAreaChart
          title="Visibility Score"
          description="Across completed audits"
          path="M0 118 C70 112 110 96 170 99 C230 102 280 72 340 76 C410 80 475 51 530 55 C575 57 600 39 620 34"
        />
        <VisibilityAreaChart
          title="Share of Voice"
          description="Brand mentions vs. competitors"
          path="M0 108 C66 98 118 104 174 86 C232 68 282 79 340 67 C402 54 460 61 526 43 C566 32 596 39 620 26"
        />
      </div>
    </div>
  );
}

function VisibilityAreaChart({
  title,
  description,
  path,
}: Readonly<{ title: string; description: string; path: string }>) {
  return (
    <div className={cn(SUPPORTING_SURFACE, 'p-4')}>
      <h4 className="text-foreground text-sm font-medium">{title}</h4>
      <p className="text-subtle mt-0.5 text-xs">{description}</p>
      <div className="relative mt-4 h-40 overflow-hidden">
        <div className="absolute inset-0 flex flex-col justify-between">
          {[0, 1, 2, 3, 4].map((line) => (
            <span key={line} className="border-border-subtle border-t" />
          ))}
        </div>
        <svg
          className="absolute inset-0 h-full w-full"
          viewBox="0 0 620 144"
          preserveAspectRatio="none"
          aria-hidden
        >
          <path d={`${path} L620 144 L0 144 Z`} fill="var(--color-accent-soft)" />
          <path
            d={path}
            fill="none"
            stroke="var(--color-accent)"
            strokeWidth="3"
            strokeLinecap="round"
          />
        </svg>
      </div>
      <div className="text-subtle mt-2 flex justify-between text-xs">
        <span>May 12</span>
        <span>Jun 9</span>
        <span>Jul 7</span>
        <span>Aug 4</span>
      </div>
    </div>
  );
}

function VisibilityContentPreview() {
  return (
    <div className="grid gap-4 p-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(260px,0.75fr)]">
      <div className={cn(SUPPORTING_SURFACE, 'overflow-hidden')}>
        <div className="border-border border-b px-4 py-3">
          <h4 className="text-foreground text-sm font-medium">Answer evidence</h4>
          <p className="text-subtle mt-0.5 text-xs">Prompt, answer, and matched entities</p>
        </div>
        <div className="p-4">
          <PreviewBadge tone="info">ChatGPT · Buying guide</PreviewBadge>
          <p className="text-foreground mt-3 text-sm font-medium">
            Which platform helps teams improve AI search visibility?
          </p>
          <div className="bg-panel mt-3 rounded-[var(--radius-control)] p-3">
            <p className="text-secondary text-sm leading-relaxed">
              Acme Corp provides evidence-grounded visibility monitoring, while Northstar focuses on
              prompt tracking and reporting.
            </p>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <PreviewBadge tone="success">Brand mentioned</PreviewBadge>
            <PreviewBadge>2 competitors</PreviewBadge>
            <PreviewBadge>3 citations</PreviewBadge>
          </div>
        </div>
      </div>
      <div className={cn(SUPPORTING_SURFACE, 'p-4')}>
        <h4 className="text-foreground text-sm font-medium">Cited content</h4>
        <p className="text-subtle mt-0.5 text-xs">Sources used in this answer</p>
        <div className="mt-4 grid gap-3">
          {[
            ['/guides/ai-visibility', 'Owned citation'],
            ['industryreview.com/tools', 'Third-party citation'],
            ['northstar.com/platform', 'Competitor citation'],
          ].map(([source, type], index) => (
            <div
              key={source}
              className="bg-panel flex items-start gap-3 rounded-[var(--radius-control)] p-3"
            >
              <span className="bg-accent-soft text-accent-text grid size-7 shrink-0 place-items-center rounded-md">
                <Link2 className="size-3.5" />
              </span>
              <div className="min-w-0">
                <p className="text-secondary truncate text-xs font-medium">{source}</p>
                <p className="text-subtle mt-1 text-xs">
                  #{index + 1} · {type}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function VisibilityFanoutPreview() {
  return (
    <div className="grid gap-4 p-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
      <div className={cn(SUPPORTING_SURFACE, 'p-4')}>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h4 className="text-foreground text-sm font-medium">Query fanout</h4>
            <p className="text-subtle mt-0.5 text-xs">Searches generated for one measured prompt</p>
          </div>
          <PreviewBadge tone="info">6 queries</PreviewBadge>
        </div>
        <p className="bg-panel text-foreground mt-4 rounded-[var(--radius-control)] p-3 text-sm font-medium">
          Best AI visibility platform for evidence-backed reporting
        </p>
        <div className="mt-3 grid gap-2">
          {[
            'AI visibility measurement methodology',
            'brand citation tracking tools',
            'AI share of voice competitors',
            'answer engine visibility reporting',
          ].map((query) => (
            <div key={query} className="text-secondary flex items-center gap-2 text-xs">
              <Search className="text-accent-text size-3.5 shrink-0" />
              <span>{query}</span>
            </div>
          ))}
        </div>
      </div>
      <div className={cn(SUPPORTING_SURFACE, 'p-4')}>
        <h4 className="text-foreground text-sm font-medium">Competitor presence</h4>
        <p className="text-subtle mt-0.5 text-xs">Brands surfaced across fanout evidence</p>
        <div className="mt-4 grid gap-3">
          {[
            ['Acme Corp', '5 of 6 queries', '83%'],
            ['Northstar', '4 of 6 queries', '67%'],
            ['Vertex Labs', '2 of 6 queries', '33%'],
          ].map(([brand, coverage, value]) => (
            <div key={brand} className="bg-panel rounded-[var(--radius-control)] p-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-secondary text-xs font-medium">{brand}</span>
                <span className="text-foreground text-xs font-medium">{value}</span>
              </div>
              <p className="text-subtle mt-1 text-xs">{coverage}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
