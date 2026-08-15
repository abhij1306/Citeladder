'use client';

import {
  ArrowUp,
  BarChart3,
  BookOpen,
  Check,
  CheckCircle2,
  Circle,
  FileText,
  Gauge,
  Globe,
  Link2,
  ListChecks,
  MessageSquareText,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

export type ProductLayerId = 'site' | 'content' | 'demand' | 'agent';

type PreviewProps = Readonly<{ phase: number; reduceMotion: boolean }>;

const PRIMARY_SURFACE = 'border-border bg-panel shadow-elevated rounded-lg border';
const SUPPORTING_SURFACE = 'border-border bg-background-alt shadow-card rounded-lg border';
const SITE_ROWS = [
  { path: '/programs/data-science', role: 'Program detail', state: '2 gaps' },
  { path: '/admissions', role: 'Admissions overview', state: 'Classified' },
  { path: '/fees', role: 'Tuition and fees', state: 'Verified' },
  { path: '/about/faculty', role: 'Faculty profile', state: '1 gap' },
] as const;
const SITE_STEPS = ['Acquire pages', 'Classify roles', 'Detect gaps', 'Verify changes'] as const;
const CONTENT_PROMPT = 'Create an FAQ brief for our admissions pages.';
const CONTENT_QUESTIONS = [
  'What documents are required?',
  'When are applications reviewed?',
  'Can international students apply?',
] as const;
const DEMAND_VIEWS = ['Overview', 'Trends', 'Mentions & Citations', 'Query Fanout'] as const;
const VISIBILITY_COMPETITORS = [
  ['Acme Corp', '62%', '1.8', 'Brand'],
  ['Northstar', '49%', '2.3', 'Competitor'],
  ['Vertex Labs', '34%', '2.9', 'Competitor'],
] as const;
const AGENT_PROMPT = 'What should we improve next?';
const AGENT_TOOL_STEPS = [
  ['Read Site findings', '12 evidence-backed gaps'],
  ['Read Demand signals', 'GSC, GA4, AI Visibility'],
  ['Prioritize next steps', 'Deterministic priority order'],
  ['Request review', 'No external action taken'],
] as const;

export function ProductPreviewPanel({
  layer,
  phase,
  reduceMotion,
}: PreviewProps & Readonly<{ layer: ProductLayerId }>) {
  if (layer === 'site') return <SitePreview phase={phase} reduceMotion={reduceMotion} />;
  if (layer === 'content') return <ContentPreview phase={phase} reduceMotion={reduceMotion} />;
  if (layer === 'demand') return <DemandPreview phase={phase} reduceMotion={reduceMotion} />;
  return <AgentPreview phase={phase} reduceMotion={reduceMotion} />;
}

function ScreenHeader({
  icon,
  title,
  description,
  action,
}: Readonly<{ icon: ReactNode; title: string; description: string; action: ReactNode }>) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-3">
        <span className="bg-accent-soft text-accent-text grid size-9 shrink-0 place-items-center rounded-md">
          {icon}
        </span>
        <div>
          <h3 className="text-foreground text-base font-semibold">{title}</h3>
          <p className="text-muted mt-0.5 text-[13px] leading-relaxed">{description}</p>
        </div>
      </div>
      {action}
    </div>
  );
}

function PreviewButton({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <span className="bg-accent text-inverse inline-flex h-8 items-center gap-1.5 rounded-sm px-3 text-[13px] font-medium shadow-xs">
      {children}
    </span>
  );
}

function PreviewBadge({
  children,
  tone = 'neutral',
}: Readonly<{ children: ReactNode; tone?: 'neutral' | 'success' | 'warning' | 'info' }>) {
  if (tone === 'neutral') return <Badge>{children}</Badge>;
  return (
    <Badge variant="status" value={tone}>
      {children}
    </Badge>
  );
}

function PhaseItem({
  visible,
  children,
  className,
}: Readonly<{
  visible: boolean;
  children: ReactNode;
  className?: string;
}>) {
  return <div className={cn(!visible && 'opacity-35', className)}>{children}</div>;
}

function useTypedPreview(text: string, active: boolean, reduceMotion: boolean) {
  const [typed, setTyped] = useState('');
  useEffect(() => {
    if (reduceMotion || !active) return;
    let cursor = 0;
    const timer = window.setInterval(() => {
      cursor += 1;
      setTyped(text.slice(0, cursor));
      if (cursor >= text.length) window.clearInterval(timer);
    }, 24);
    return () => window.clearInterval(timer);
  }, [active, reduceMotion, text]);
  return reduceMotion || !active ? text : typed;
}

function MetricStrip({
  items,
}: Readonly<{ items: ReadonlyArray<{ label: string; value: string; detail: string }> }>) {
  return (
    <div className="border-border bg-panel shadow-card mt-4 grid grid-cols-2 overflow-hidden rounded-md border lg:grid-cols-4">
      {items.map((item, index) => (
        <div
          key={item.label}
          className={cn(
            'px-3 py-2.5',
            index % 2 !== 0 && 'border-border-subtle border-l',
            index >= 2 && 'border-border-subtle border-t lg:border-t-0',
            index === 2 && 'lg:border-l',
          )}
        >
          <p className="text-subtle text-[11px] font-medium">{item.label}</p>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className="text-foreground text-base font-semibold tabular-nums">
              {item.value}
            </span>
            <span className="text-muted text-[10px]">{item.detail}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function SitePreview({ phase }: PreviewProps) {
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
              <h4 className="text-foreground text-sm font-semibold">URL inventory</h4>
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
                  <p className="text-foreground truncate text-[13px] font-medium">{row.path}</p>
                  <p className="text-subtle mt-0.5 text-[11px]">HTML · visible evidence · schema</p>
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
            <h4 className="text-foreground text-sm font-semibold">Acquisition run</h4>
            <span className="text-subtle text-[11px] tabular-nums">Preview data</span>
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
                    <p className="text-secondary text-[13px] font-medium">{step}</p>
                    <p className="text-subtle mt-0.5 text-[11px]">
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

function ContentPreview({ phase, reduceMotion }: PreviewProps) {
  const typedPrompt = useTypedPreview(CONTENT_PROMPT, phase === 0, reduceMotion);

  return (
    <div data-preview-layer="content" className="p-4 sm:p-5">
      <ScreenHeader
        icon={<FileText className="size-4" aria-hidden />}
        title="Content Intelligence"
        description="A conversational workspace for grounded briefs, FAQs, drafts, and review."
        action={<PreviewBadge tone="success">Project facts connected</PreviewBadge>}
      />

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(250px,0.75fr)]">
        <section className={cn(PRIMARY_SURFACE, 'flex min-h-[500px] flex-col overflow-hidden')}>
          <div className="border-border flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
            <div>
              <div className="flex items-center gap-2">
                <h4 className="text-foreground text-sm font-semibold">Admissions content</h4>
                <PreviewBadge tone={phase >= 3 ? 'success' : 'info'}>
                  {phase >= 3 ? 'Ready for review' : 'Working'}
                </PreviewBadge>
              </div>
              <p className="text-subtle mt-1 text-xs">7 evidence records in context</p>
            </div>
            <span className="text-muted text-xs">Conversation</span>
          </div>
          <div className="flex flex-1 flex-col justify-end gap-3 p-4">
            {phase >= 1 ? (
              <div className="bg-accent text-inverse shadow-card ml-auto max-w-[78%] rounded-lg px-4 py-3 text-[13px] leading-relaxed">
                {CONTENT_PROMPT}
              </div>
            ) : null}

            {phase >= 1 ? (
              <div className="border-border bg-panel shadow-card max-w-[88%] rounded-lg border px-4 py-3">
                <div className="text-accent-text flex items-center gap-2 text-xs font-medium">
                  <Search className="size-3.5" aria-hidden />
                  Read Site Health gaps
                </div>
                <p className="text-secondary mt-2 text-[13px] leading-relaxed">
                  I found three uncovered admissions questions and matched them to persisted project
                  evidence.
                </p>
              </div>
            ) : null}

            {phase >= 2 ? (
              <div className="border-border bg-panel shadow-card max-w-[88%] rounded-lg border px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-foreground text-sm font-semibold">Admissions FAQ brief</p>
                  <PreviewBadge tone="success">Grounded</PreviewBadge>
                </div>
                <div className="mt-3 grid gap-2">
                  {CONTENT_QUESTIONS.map((question) => (
                    <div key={question} className="text-secondary flex items-center gap-2 text-xs">
                      <Check className="text-success-text size-3.5 shrink-0" aria-hidden />
                      {question}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {phase >= 3 ? (
              <div className="flex max-w-[88%] flex-wrap items-center gap-2">
                <span className="border-border-strong bg-panel text-secondary inline-flex h-8 items-center rounded-sm border px-3 text-xs font-medium shadow-xs">
                  View evidence
                </span>
                <span className="bg-accent text-inverse inline-flex h-8 items-center rounded-sm px-3 text-xs font-medium shadow-xs">
                  Review brief
                </span>
              </div>
            ) : null}
          </div>
          <div className="border-border bg-background-alt border-t p-3">
            <div className="border-border-strong bg-panel text-muted flex h-10 items-center gap-3 rounded-md border px-3 text-[13px] shadow-xs">
              <span className="min-w-0 flex-1 truncate">
                {phase === 0 ? typedPrompt : 'Ask Content Intelligence…'}
                {phase === 0 && typedPrompt.length < CONTENT_PROMPT.length ? (
                  <span
                    className="bg-accent ml-0.5 inline-block h-4 w-px align-middle"
                    aria-hidden
                  />
                ) : null}
              </span>
              <span className="bg-accent text-inverse grid size-7 place-items-center rounded-md">
                <ArrowUp className="size-3.5" aria-hidden />
              </span>
            </div>
          </div>
        </section>

        <section className={cn(SUPPORTING_SURFACE, 'p-4')}>
          <div className="flex items-center gap-2">
            <BookOpen className="text-accent-text size-4" aria-hidden />
            <h4 className="text-foreground text-sm font-semibold">Evidence guardrail</h4>
          </div>
          <div className="mt-4 grid gap-3">
            {[
              ['Project facts', '4 assertions'],
              ['Owned pages', '3 sources'],
              ['Unsupported claims', phase >= 2 ? 'None found' : 'Checking'],
              ['Schema parity', phase >= 3 ? 'Matched' : 'Queued'],
            ].map(([label, value], index) => (
              <PhaseItem
                key={label}
                visible={phase >= Math.min(index, 3)}
                className="flex items-center justify-between gap-3"
              >
                <span className="text-muted text-xs">{label}</span>
                <span className="text-foreground text-xs font-medium">{value}</span>
              </PhaseItem>
            ))}
          </div>
          <div className="border-border mt-4 border-t pt-4">
            <p className="text-subtle text-[11px] leading-relaxed">
              Saving content remains a human decision. The preview stops at review.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}

function DemandPreview({ phase }: PreviewProps) {
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
                  'relative shrink-0 pb-3 text-[13px] font-medium',
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

        {activeView === 'Overview' ? <VisibilityOverviewPreview /> : null}
        {activeView === 'Trends' ? <VisibilityTrendsPreview /> : null}
        {activeView === 'Mentions & Citations' ? <VisibilityContentPreview /> : null}
        {activeView === 'Query Fanout' ? <VisibilityFanoutPreview /> : null}
      </section>
    </div>
  );
}

function VisibilityOverviewPreview() {
  return (
    <div className="p-4">
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-2">
        <p className="text-secondary min-w-0 flex-1 text-sm">
          Acme Corp is mentioned in <strong className="text-foreground font-semibold">62%</strong>{' '}
          of measured answers.
        </p>
        <div className="flex gap-5 text-xs">
          <span className="text-muted">
            Visibility <b className="text-foreground">62%</b>
          </span>
          <span className="text-muted">
            Position <b className="text-foreground">1.8</b>
          </span>
          <span className="text-muted">
            Rank <b className="text-foreground">#1</b>
          </span>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(250px,0.75fr)]">
        <div className={cn(SUPPORTING_SURFACE, 'overflow-hidden')}>
          <div className="border-border border-b px-4 py-3">
            <h4 className="text-foreground text-sm font-semibold">Competitors</h4>
            <p className="text-subtle mt-0.5 text-xs">Compared across the same answers</p>
          </div>
          <div className="border-border text-muted grid grid-cols-[minmax(0,1fr)_70px_70px] border-b px-4 py-2 text-[11px] font-medium">
            <span>Brand</span>
            <span>Share</span>
            <span>Position</span>
          </div>
          {VISIBILITY_COMPETITORS.map(([name, share, position, type]) => (
            <div
              key={name}
              className="border-border-subtle grid grid-cols-[minmax(0,1fr)_70px_70px] items-center border-b px-4 py-3 last:border-b-0"
            >
              <div className="min-w-0">
                <p className="text-secondary truncate text-[13px] font-medium">{name}</p>
                <p className="text-subtle mt-0.5 text-[11px]">{type}</p>
              </div>
              <span className="text-foreground text-xs font-semibold tabular-nums">{share}</span>
              <span className="text-secondary text-xs tabular-nums">{position}</span>
            </div>
          ))}
        </div>

        <div className={cn(SUPPORTING_SURFACE, 'p-4')}>
          <h4 className="text-foreground text-sm font-semibold">Share of answers</h4>
          <p className="text-subtle mt-0.5 text-xs">Brand mentions by engine</p>
          <div className="mt-5 grid gap-4">
            {[
              ['ChatGPT', '71%', 'w-[71%]'],
              ['Gemini', '59%', 'w-[59%]'],
              ['Claude', '48%', 'w-[48%]'],
            ].map(([engine, value, width]) => (
              <div key={engine}>
                <div className="mb-1.5 flex justify-between text-xs">
                  <span className="text-secondary">{engine}</span>
                  <span className="text-foreground font-medium">{value}</span>
                </div>
                <div className="bg-neutral-bg h-2 overflow-hidden rounded-full">
                  <span className={cn('bg-accent block h-full rounded-full', width)} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
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
      <h4 className="text-foreground text-sm font-semibold">{title}</h4>
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
      <div className="text-subtle mt-2 flex justify-between text-[11px]">
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
          <h4 className="text-foreground text-sm font-semibold">Answer evidence</h4>
          <p className="text-subtle mt-0.5 text-xs">Prompt, answer, and matched entities</p>
        </div>
        <div className="p-4">
          <PreviewBadge tone="info">ChatGPT · Buying guide</PreviewBadge>
          <p className="text-foreground mt-3 text-[13px] font-medium">
            Which platform helps teams improve AI search visibility?
          </p>
          <div className="border-border bg-panel mt-3 rounded-md border p-3 shadow-xs">
            <p className="text-secondary text-[13px] leading-relaxed">
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
        <h4 className="text-foreground text-sm font-semibold">Cited content</h4>
        <p className="text-subtle mt-0.5 text-xs">Sources used in this answer</p>
        <div className="mt-4 grid gap-3">
          {[
            ['/guides/ai-visibility', 'Owned citation'],
            ['industryreview.com/tools', 'Third-party citation'],
            ['northstar.com/platform', 'Competitor citation'],
          ].map(([source, type], index) => (
            <div
              key={source}
              className="border-border bg-panel flex items-start gap-3 rounded-md border p-3 shadow-xs"
            >
              <span className="bg-accent-soft text-accent-text grid size-7 shrink-0 place-items-center rounded-md">
                <Link2 className="size-3.5" />
              </span>
              <div className="min-w-0">
                <p className="text-secondary truncate text-xs font-medium">{source}</p>
                <p className="text-subtle mt-1 text-[11px]">
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
            <h4 className="text-foreground text-sm font-semibold">Query fanout</h4>
            <p className="text-subtle mt-0.5 text-xs">Searches generated for one measured prompt</p>
          </div>
          <PreviewBadge tone="info">6 queries</PreviewBadge>
        </div>
        <p className="border-border bg-panel text-foreground mt-4 rounded-md border p-3 text-[13px] font-medium shadow-xs">
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
        <h4 className="text-foreground text-sm font-semibold">Competitor presence</h4>
        <p className="text-subtle mt-0.5 text-xs">Brands surfaced across fanout evidence</p>
        <div className="mt-4 grid gap-3">
          {[
            ['Acme Corp', '5 of 6 queries', '83%'],
            ['Northstar', '4 of 6 queries', '67%'],
            ['Vertex Labs', '2 of 6 queries', '33%'],
          ].map(([brand, coverage, value]) => (
            <div key={brand} className="border-border bg-panel rounded-md border p-3 shadow-xs">
              <div className="flex items-center justify-between gap-3">
                <span className="text-secondary text-xs font-medium">{brand}</span>
                <span className="text-foreground text-xs font-semibold">{value}</span>
              </div>
              <p className="text-subtle mt-1 text-[11px]">{coverage}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function AgentPreview({ phase, reduceMotion }: PreviewProps) {
  const typedPrompt = useTypedPreview(AGENT_PROMPT, phase === 0, reduceMotion);

  return (
    <div data-preview-layer="agent" className="p-4 sm:p-5">
      <ScreenHeader
        icon={<Sparkles className="size-4" aria-hidden />}
        title="Growth Agent"
        description="Bounded orchestration over typed Site, Content, and Demand tools."
        action={
          <PreviewBadge tone={phase >= 3 ? 'success' : 'info'}>
            {phase >= 3 ? 'Roadmap ready' : 'Working'}
          </PreviewBadge>
        }
      />

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(270px,0.75fr)]">
        <section className={cn(PRIMARY_SURFACE, 'flex min-h-[390px] flex-col overflow-hidden')}>
          <div className="border-border flex items-center gap-3 border-b px-4 py-3">
            <span className="bg-accent-soft text-accent-text grid size-7 place-items-center rounded-md">
              <MessageSquareText className="size-3.5" />
            </span>
            <div>
              <h4 className="text-foreground text-sm font-semibold">Growth planning</h4>
              <p className="text-subtle mt-0.5 text-[11px]">Selective context · project scoped</p>
            </div>
          </div>
          <div className="flex-1 p-4">
            {phase >= 1 ? (
              <div className="bg-accent text-inverse shadow-card mb-4 ml-auto max-w-[78%] rounded-lg px-4 py-3 text-[13px] leading-relaxed">
                {AGENT_PROMPT}
              </div>
            ) : null}
            <div className="grid gap-2.5">
              {AGENT_TOOL_STEPS.map(([label, detail], index) => (
                <PhaseItem key={label} visible={phase >= index} className="flex items-center gap-3">
                  <span
                    className={cn(
                      'grid size-6 shrink-0 place-items-center rounded-full',
                      phase > index || phase === 3
                        ? 'bg-success-bg text-success-text'
                        : 'bg-info-bg text-info-text',
                    )}
                  >
                    {phase > index || phase === 3 ? (
                      <Check className="size-3.5" />
                    ) : (
                      <RefreshCw className="size-3 animate-spin" />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-secondary text-xs font-medium">{label}</p>
                    <p className="text-subtle mt-0.5 truncate text-[11px]">{detail}</p>
                  </div>
                  <span className="text-subtle text-[11px] tabular-nums">
                    {phase > index ? `${index + 1}s` : ''}
                  </span>
                </PhaseItem>
              ))}
            </div>

            <PhaseItem
              visible={phase >= 3}
              className="bg-background-alt border-border shadow-card mt-4 rounded-lg border p-4"
            >
              <div className="flex items-center gap-2">
                <CheckCircle2 className="text-success-text size-4" />
                <p className="text-foreground text-sm font-semibold">Recommended next action</p>
              </div>
              <p className="text-secondary mt-2 text-[13px] leading-relaxed">
                Close the admissions question gap with an evidence-backed FAQ brief, then verify it
                after publication.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <PreviewBadge>Site evidence</PreviewBadge>
                <PreviewBadge>Demand signal</PreviewBadge>
                <PreviewBadge>Pack rule</PreviewBadge>
              </div>
            </PhaseItem>
          </div>
          <div className="border-border bg-background-alt border-t p-3">
            <div className="border-border-strong bg-panel text-muted flex h-10 items-center gap-3 rounded-md border px-3 text-[13px] shadow-xs">
              <span className="min-w-0 flex-1 truncate">
                {phase === 0 ? typedPrompt : 'Ask Growth Agent…'}
                {phase === 0 && typedPrompt.length < AGENT_PROMPT.length ? (
                  <span
                    className="bg-accent ml-0.5 inline-block h-4 w-px align-middle"
                    aria-hidden
                  />
                ) : null}
              </span>
              <span className="bg-accent text-inverse grid size-7 place-items-center rounded-md">
                <ArrowUp className="size-3.5" aria-hidden />
              </span>
            </div>
          </div>
        </section>

        <section className={cn(SUPPORTING_SURFACE, 'p-4')}>
          <div className="flex items-center justify-between gap-3">
            <h4 className="text-foreground text-sm font-semibold">Priority roadmap</h4>
            <ListChecks className="text-muted size-4" />
          </div>
          <div className="mt-3 grid gap-2.5">
            {[
              ['Admissions FAQ coverage', 'Site + Demand'],
              ['Program proof gaps', 'Site'],
              ['Citation-ready comparisons', 'Demand + Content'],
            ].map(([title, source], index) => (
              <PhaseItem
                key={title}
                visible={phase >= Math.min(index + 1, 3)}
                className="bg-panel border-border rounded-md border p-3 shadow-xs"
              >
                <div className="flex items-start gap-3">
                  <span className="text-accent-text text-xs font-semibold tabular-nums">
                    {index + 1}
                  </span>
                  <div className="min-w-0">
                    <p className="text-secondary text-xs font-medium">{title}</p>
                    <p className="text-subtle mt-1 text-[11px]">{source} · evidence linked</p>
                  </div>
                </div>
              </PhaseItem>
            ))}
          </div>
          <PhaseItem visible={phase >= 3} className="mt-4 grid grid-cols-2 gap-2">
            <span className="border-border-strong bg-panel text-secondary inline-flex h-8 items-center justify-center rounded-sm border text-xs font-medium shadow-xs">
              View evidence
            </span>
            <span className="bg-accent text-inverse inline-flex h-8 items-center justify-center rounded-sm text-xs font-medium shadow-xs">
              Review brief
            </span>
          </PhaseItem>
          <div className="border-border mt-4 flex items-start gap-2 border-t pt-3">
            <ShieldCheck className="text-success-text mt-0.5 size-3.5 shrink-0" />
            <p className="text-subtle text-[11px] leading-relaxed">
              The agent explains and prepares. You decide when content is saved or an audit runs.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
