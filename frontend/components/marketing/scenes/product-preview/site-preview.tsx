import { Check, Circle, Globe, RefreshCw } from 'lucide-react';

import { cn } from '@/lib/utils';

import {
  MetricStrip,
  PhaseItem,
  PreviewBadge,
  PreviewButton,
  PRIMARY_SURFACE,
  ScreenHeader,
  SUPPORTING_SURFACE,
  type PreviewProps,
} from './shared';

const SITE_ROWS = [
  { path: '/programs/data-science', role: 'Program detail', state: '2 gaps' },
  { path: '/admissions', role: 'Admissions overview', state: 'Classified' },
  { path: '/fees', role: 'Tuition and fees', state: 'Verified' },
  { path: '/about/faculty', role: 'Faculty profile', state: '1 gap' },
] as const;
const SITE_STEPS = ['Acquire pages', 'Classify roles', 'Detect gaps', 'Verify changes'] as const;

export function SitePreview({ phase }: PreviewProps) {
  return (
    <div data-preview-layer="site" className="p-4 sm:p-5">
      <ScreenHeader
        icon={<Globe className="size-4" aria-hidden />}
        title="Site Health"
        description="Inventory, evidence, page understanding, gaps, and recrawl verification."
        action={
          <PreviewButton>
            <RefreshCw className={cn('size-3', phase < 3 && 'animate-spin')} aria-hidden />
            Recrawl
          </PreviewButton>
        }
      />
      <MetricStrip
        items={[
          { label: 'Owned corpus', value: phase >= 0 ? '128' : '—', detail: 'pages' },
          { label: 'Role coverage', value: phase >= 1 ? '91%' : '—', detail: 'classified' },
          { label: 'Open gaps', value: phase >= 2 ? '12' : '—', detail: 'evidence-backed' },
          { label: 'Verified', value: phase >= 3 ? '8' : '—', detail: 'after recrawl' },
        ]}
      />

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(240px,0.75fr)]">
        <section className={cn(PRIMARY_SURFACE, 'overflow-hidden')}>
          <div className="border-border flex items-center justify-between gap-3 border-b px-4 py-3">
            <div>
              <h4 className="text-foreground text-sm font-medium">URL inventory</h4>
              <p className="text-subtle mt-0.5 text-xs">Current compatible snapshot</p>
            </div>
            <PreviewBadge tone={phase >= 3 ? 'success' : 'info'}>
              {phase >= 3 ? 'Snapshot ready' : 'Analyzing'}
            </PreviewBadge>
          </div>
          <div className="divide-border divide-y">
            {SITE_ROWS.map((row, index) => (
              <PhaseItem
                key={row.path}
                visible={phase >= Math.min(index, 2)}
                className="grid grid-cols-[minmax(0,1.4fr)_minmax(110px,0.8fr)_auto] items-center gap-3 px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="text-foreground truncate text-sm font-medium">{row.path}</p>
                  <p className="text-subtle mt-0.5 text-xs">HTML · visible evidence · schema</p>
                </div>
                <span className="text-muted hidden truncate text-xs sm:block">{row.role}</span>
                <PreviewBadge
                  tone={
                    row.state === 'Verified'
                      ? 'success'
                      : row.state.includes('gap')
                        ? 'warning'
                        : 'neutral'
                  }
                >
                  {row.state}
                </PreviewBadge>
              </PhaseItem>
            ))}
          </div>
        </section>

        <section className={cn(SUPPORTING_SURFACE, 'p-4')}>
          <div className="flex items-center justify-between gap-3">
            <h4 className="text-foreground text-sm font-medium">Acquisition run</h4>
            <span className="text-subtle text-xs tabular-nums">Preview data</span>
          </div>
          <div className="mt-4 grid gap-3">
            {SITE_STEPS.map((step, index) => {
              const complete = phase > index || phase === 3;
              const active = phase === index && phase < 3;
              return (
                <PhaseItem key={step} visible={phase >= index} className="flex items-start gap-3">
                  <span
                    className={cn(
                      'mt-0.5 grid size-5 shrink-0 place-items-center rounded-full',
                      complete && 'bg-success-bg text-success-text',
                      active && 'bg-info-bg text-info-text',
                      !complete && !active && 'bg-neutral-bg text-subtle',
                    )}
                  >
                    {complete ? (
                      <Check className="size-3" />
                    ) : active ? (
                      <RefreshCw className="size-3 animate-spin" />
                    ) : (
                      <Circle className="size-2.5" />
                    )}
                  </span>
                  <div>
                    <p className="text-secondary text-sm font-medium">{step}</p>
                    <p className="text-subtle mt-0.5 text-xs">
                      {complete ? 'Persisted with provenance' : active ? 'Working now' : 'Queued'}
                    </p>
                  </div>
                </PhaseItem>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
