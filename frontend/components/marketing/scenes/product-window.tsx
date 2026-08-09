'use client';

import { type ReactNode, useRef, useState } from 'react';
import { useGSAP } from '@gsap/react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { AnimatePresence, m, useReducedMotion } from 'motion/react';
import {
  BarChart3,
  Bot,
  Eye,
  FileSearch,
  Search,
  ShieldCheck,
  Zap,
  TrendingUp,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { ICONS } from '@/lib/icons';
import { useTourAutoplay } from '@/lib/hooks/use-tour-autoplay';
import { Meta } from '../primitives/label';
import { TourStepper } from '../primitives/tour-stepper';

if (typeof window !== 'undefined') {
  gsap.registerPlugin(ScrollTrigger);
}

/**
 * Animated number component powered by GSAP ScrollTrigger.
 */
function AnimatedNumber({ value }: { value: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [displayValue, setDisplayValue] = useState(value);
  const reduceMotion = useReducedMotion();

  useGSAP(
    () => {
      const numericTarget = parseFloat(value.replace(/,/g, ''));
      if (isNaN(numericTarget) || reduceMotion) {
        setDisplayValue(value);
        return;
      }

      const obj = { val: 0 };
      const isDecimal = value.includes('.');
      const isComma = value.includes(',');

      gsap.to(obj, {
        val: numericTarget,
        duration: 1.8,
        ease: 'power2.out',
        scrollTrigger: {
          trigger: ref.current,
          start: 'top 85%',
          once: true,
        },
        onUpdate: () => {
          if (isDecimal) {
            setDisplayValue(obj.val.toFixed(1));
          } else if (isComma) {
            setDisplayValue(Math.floor(obj.val).toLocaleString('en-US'));
          } else {
            setDisplayValue(Math.floor(obj.val).toString());
          }
        },
      });
    },
    { scope: ref, dependencies: [value, reduceMotion] },
  );

  return <span ref={ref}>{displayValue}</span>;
}

const EASE_OUT = [0.16, 1, 0.3, 1] as const;
const STEP_DURATION = 6000;

// Compact relevant sidebar items to reduce overall height
const COMPACT_NAV_GROUPS = [
  {
    title: 'Analyze',
    items: [
      { label: 'Visibility', icon: ICONS.visibility },
      { label: 'AI Referrals', icon: ICONS.analytics },
      { label: 'Traffic', icon: ICONS.traffic },
      { label: 'Prompts', icon: ICONS.prompts },
    ],
  },
  {
    title: 'Improve',
    items: [
      { label: 'Content', icon: ICONS.content },
      { label: 'Site health', icon: ICONS.siteHealth },
      { label: 'Opportunities', icon: ICONS.opportunities },
    ],
  },
] as const;

const STORY_STEPS = [
  {
    id: 'observe',
    num: '01',
    label: '1. Observe',
    navLabel: 'Visibility',
    shiftTitle: 'Shift Fact #1: Buyers ask AI before browsing',
    productSolution:
      'Track real buyer prompts across ChatGPT, Gemini, Claude & Perplexity with trend graphs',
    icon: Eye,
  },
  {
    id: 'trace',
    num: '02',
    label: '2. Trace',
    navLabel: 'AI Referrals',
    shiftTitle: 'Shift Fact #2: AI answers cite, they don’t rank',
    productSolution:
      'Trace every score back to exact LLM answer text & 100% reproducible source citations',
    icon: FileSearch,
  },
  {
    id: 'benchmark',
    num: '03',
    label: '3. Benchmark',
    navLabel: 'Prompts',
    shiftTitle: 'Shift Fact #3: You can’t fix what you can’t see',
    productSolution:
      'Benchmark your brand’s Share of Voice & citation graphs against market competitors',
    icon: BarChart3,
  },
  {
    id: 'optimize',
    num: '04',
    label: '4. Optimize',
    navLabel: 'Opportunities',
    shiftTitle: 'Navigating The Shift',
    // "high-ROI" asserts an outcome nothing here measures. The prioritisation
    // is real and deterministic; the return on it is not ours to claim.
    productSolution: 'Turn visibility gaps into prioritized content & schema updates',
    icon: Zap,
  },
] as const;

interface MetricItem {
  label: string;
  value: string;
  delta?: string;
}

const METRICS: readonly MetricItem[] = [
  { label: 'Visibility index', value: '72.4', delta: '+4.8' },
  { label: 'Share of voice', value: '18.6', delta: '+2.1' },
  { label: 'Answers observed', value: '1,248' },
];

const EVIDENCE = {
  answer:
    '“For enterprise analytics, teams most often cite CiteLadder alongside market leaders for its verifiable citation tracking…”',
  chain: [
    ['Provider', 'ChatGPT 4.5'],
    ['Artifact', 'a3f9c1'],
    ['Analyzer', 'visibility-v4.2'],
    ['Reproducible', 'yes'],
  ],
} as const;

const BENCHMARK_ROWS: readonly {
  label: string;
  value: string;
  width: string;
  own?: boolean;
  opacity?: string;
}[] = [
  {
    label: 'Acme Corp (Your Brand)',
    value: '38.4% Share (#1 Lead)',
    width: 'w-[38.4%]',
    own: true,
  },
  { label: 'Competitor A', value: '28.1%', width: 'w-[28.1%]', opacity: 'opacity-60' },
  { label: 'Competitor B', value: '19.5%', width: 'w-[19.5%]', opacity: 'opacity-40' },
] as const;

const OPPORTUNITY_ROWS = [
  {
    title: 'Update Deprecated Docs Cited by ChatGPT',
    detail: 'Increases ChatGPT recommendation score by +14%',
    action: 'Fix Now',
    icon: Zap,
    iconClassName: 'bg-warning-bg text-warning-text border-warning-border',
    actionClassName: 'bg-accent text-white',
  },
  {
    title: 'Publish Enterprise Comparison Table for Gemini',
    detail: 'Captures missing citations in enterprise buyer queries',
    action: 'View Draft',
    icon: Bot,
    iconClassName: 'bg-accent-subtle text-accent-text border-accent-border',
    actionClassName: 'bg-panel border-border-subtle text-foreground border',
  },
] as const;

function FrameView({
  title,
  status,
  reduceMotion,
  children,
  className = 'space-y-4',
}: Readonly<{
  title: string;
  status: ReactNode;
  reduceMotion: boolean | null;
  children: ReactNode;
  className?: string;
}>) {
  return (
    <m.div
      initial={false}
      animate={{ opacity: 1, y: 0 }}
      exit={reduceMotion ? undefined : { opacity: 0, y: -6 }}
      transition={{ duration: 0.25, ease: EASE_OUT }}
      className={className}
    >
      <div className="flex items-center justify-between">
        <p className="font-display text-foreground text-sm font-medium">{title}</p>
        {status}
      </div>
      {children}
    </m.div>
  );
}

function FrameCard({ children, className }: Readonly<{ children: ReactNode; className?: string }>) {
  return (
    <div className={cn('bg-background-alt border-border-subtle rounded-md border p-4', className)}>
      {children}
    </div>
  );
}

/**
 * Compact, Authentic CiteLadder Product Showcase Canvas with Real Trend Graphs.
 * Fits comfortably on screen with streamlined sidebar, real-time SVG charts,
 * and a narrative tour connecting "The Shift" to "How CiteLadder Helps You Win".
 */
const GRID_COLS_MAP: Record<number, string> = {
  1: 'grid-cols-1',
  2: 'grid-cols-2',
  3: 'grid-cols-3',
  4: 'grid-cols-4',
};

// react-doctor-disable-next-line react-doctor/no-giant-component -- one synchronized GSAP/stepper scene owns all four mutually exclusive frames and their shared transition state.
export function ProductWindow() {
  const containerRef = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();
  const { activeStep, isPlaying, selectStep, togglePlay } = useTourAutoplay(
    STORY_STEPS.length,
    STEP_DURATION,
  );

  const currentStep = STORY_STEPS[activeStep];

  return (
    <div
      ref={containerRef}
      data-testid="product-window"
      className="app-type-scale bg-panel shadow-card mx-auto max-w-5xl rounded-lg p-4 sm:p-5"
    >
      {/* Storytelling Tour Stepper */}
      <div className="bg-background-alt border-border-subtle mb-5 rounded-lg border p-4 sm:p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <TourStepper
            steps={STORY_STEPS}
            activeStep={activeStep}
            isPlaying={isPlaying}
            onSelectStep={selectStep}
            onTogglePlay={togglePlay}
            compact
          />
        </div>

        <div className="border-border-subtle mt-4 flex items-center justify-between border-t pt-3 text-xs">
          <div className="flex items-center gap-3 truncate">
            <span className="bg-success size-1.5 shrink-0 animate-pulse rounded-full" />
            <span className="text-accent-text font-mono font-medium uppercase">
              {currentStep.label.split('.')[1]?.trim()}:
            </span>
            <span className="text-muted truncate font-medium">
              {currentStep.productSolution} — every score opens to the answer behind it.
            </span>
          </div>
        </div>
      </div>

      {/* Compact Product Layout Canvas */}
      <div
        aria-hidden
        className="bg-background-alt grid min-h-[280px] items-stretch gap-0 overflow-hidden lg:grid-cols-[12rem_minmax(0,1fr)]"
      >
        {/* Streamlined Authentic Sidebar */}
        <aside className="bg-panel border-border-subtle hidden flex-col justify-between border-r p-4 lg:flex">
          <div className="space-y-5">
            {COMPACT_NAV_GROUPS.map((group) => (
              <div key={group.title} className="space-y-2">
                <p className="text-muted mb-2 px-3 font-mono text-xs font-medium uppercase">
                  {group.title}
                </p>
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const isActive = item.label === currentStep.navLabel;

                  return (
                    <div
                      key={item.label}
                      className={`relative flex items-center gap-3 rounded-md px-3 py-2 text-xs font-medium transition-colors ${
                        isActive ? 'bg-accent-subtle text-accent-text font-medium' : 'text-muted'
                      }`}
                    >
                      {isActive && (
                        <span className="bg-accent absolute top-1 bottom-1 left-0 w-0.5 rounded-r-md" />
                      )}
                      <Icon className="size-4 shrink-0" />
                      <span className="truncate">{item.label}</span>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </aside>

        {/* Compact Main Workspace Area with Real Graphs */}
        <div className="bg-panel flex flex-col justify-between p-5 sm:p-5">
          <AnimatePresence mode="wait">
            {activeStep === 0 && (
              <FrameView
                key="observe-view"
                reduceMotion={reduceMotion}
                title="Visibility Overview & Trend Graph"
                status={
                  <span className="text-accent-text flex items-center gap-2 font-mono text-xs font-medium">
                    <TrendingUp className="size-3" /> Cross-Run Trend
                  </span>
                }
                className="space-y-5"
              >
                {/* Metrics Row */}
                <div
                  className={cn(
                    'border-border-subtle bg-panel grid rounded-md border',
                    GRID_COLS_MAP[METRICS.length] ?? 'grid-cols-3',
                  )}
                >
                  {METRICS.map((metric, index) => (
                    <div
                      key={metric.label}
                      className={`p-4 sm:p-4 ${
                        index < METRICS.length - 1 ? 'border-border-subtle border-r' : ''
                      }`}
                    >
                      <Meta as="p" className="text-muted text-xs">
                        {metric.label}
                      </Meta>
                      <b className="text-foreground mt-2 block font-mono text-base leading-none font-medium tabular-nums">
                        <AnimatedNumber value={metric.value} />
                        {'delta' in metric && metric.delta && (
                          <small className="text-success-text ml-2 font-mono text-xs font-medium tabular-nums">
                            {metric.delta}
                          </small>
                        )}
                      </b>
                    </div>
                  ))}
                </div>

                {/* SVG Trend Graph (Real Product Chart) */}
                <FrameCard>
                  <div className="text-muted mb-3 flex items-center justify-between font-mono text-xs">
                    <span>Visibility Score Trend (Last 8 Audits)</span>
                    <span className="text-success-text font-medium">72.4% Peak</span>
                  </div>
                  <div className="relative flex h-20 w-full items-end pt-3">
                    {/* SVG Curve Line */}
                    <svg
                      className="text-accent h-full w-full overflow-visible"
                      viewBox="0 0 300 60"
                      preserveAspectRatio="none"
                    >
                      <path
                        d="M 0,45 Q 40,38 80,32 T 160,22 T 240,15 T 300,8"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                      />
                      <circle cx="300" cy="8" r="3.5" fill="currentColor" />
                    </svg>
                  </div>
                  <div className="text-muted border-border-subtle mt-2 flex justify-between border-t pt-2 font-mono text-xs">
                    <span>Apr 01</span>
                    <span>May 15</span>
                    <span>Jun 30 (Latest Run)</span>
                  </div>
                </FrameCard>
              </FrameView>
            )}

            {activeStep === 1 && (
              <FrameView
                key="trace-view"
                reduceMotion={reduceMotion}
                title="Answers & Evidence Trace"
                status={
                  <span className="text-accent-text flex items-center gap-2 font-mono text-xs font-medium">
                    <ShieldCheck className="text-success-text size-3" /> 100% Verifiable
                  </span>
                }
              >
                <FrameCard>
                  <div className="text-muted flex items-center justify-between text-xs">
                    <span className="text-foreground flex items-center gap-2 font-medium">
                      <Search className="text-accent-text size-3" />
                      Observed Answer Text
                    </span>
                    <span className="text-accent-text font-mono font-medium tabular-nums">
                      Visibility score: <AnimatedNumber value="72.4" />
                    </span>
                  </div>

                  <p className="text-foreground mt-3 text-xs leading-relaxed font-medium">
                    {EVIDENCE.answer}
                  </p>

                  <div className="mt-4 flex flex-wrap gap-2">
                    {EVIDENCE.chain.map(([label, value]) => (
                      <span
                        key={label}
                        className="bg-panel border-border-subtle text-success-text rounded-full border px-3 py-2 font-mono text-xs"
                      >
                        <span className="text-muted uppercase">{label}:</span>{' '}
                        <span className="font-medium">{value}</span>
                      </span>
                    ))}
                  </div>
                </FrameCard>
              </FrameView>
            )}

            {activeStep === 2 && (
              <FrameView
                key="benchmark-view"
                reduceMotion={reduceMotion}
                title="Share of Voice & Competitive Chart"
                status={
                  <span className="text-accent-text font-mono text-xs font-medium">
                    Market Share Comparison
                  </span>
                }
              >
                <FrameCard className="space-y-4">
                  {BENCHMARK_ROWS.map((row) => (
                    <div key={row.label}>
                      <div
                        className={cn(
                          'mb-2 flex justify-between text-xs',
                          row.own ? 'font-medium' : 'text-muted',
                        )}
                      >
                        <span className={row.own ? 'text-foreground' : undefined}>{row.label}</span>
                        <span className={cn('font-mono', row.own && 'text-accent-text')}>
                          {row.value}
                        </span>
                      </div>
                      <div className="bg-background-alt h-2 w-full overflow-hidden rounded-full">
                        <div
                          className={cn(
                            'h-full rounded-full',
                            row.own ? 'bg-accent' : 'bg-border',
                            row.width,
                            row.opacity,
                          )}
                        />
                      </div>
                    </div>
                  ))}
                </FrameCard>
              </FrameView>
            )}

            {activeStep === 3 && (
              <FrameView
                key="optimize-view"
                reduceMotion={reduceMotion}
                title="Opportunities & Action Recommendations"
                status={
                  <span className="text-accent-text font-mono text-xs font-medium">
                    High-Impact Moves
                  </span>
                }
              >
                {OPPORTUNITY_ROWS.map((row) => {
                  const Icon = row.icon;
                  return (
                    <FrameCard key={row.title} className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className={cn('rounded-md border p-2', row.iconClassName)}>
                          <Icon className="size-3" />
                        </span>
                        <div>
                          <span className="text-foreground block text-xs font-medium">
                            {row.title}
                          </span>
                          <span className="text-muted text-xs">{row.detail}</span>
                        </div>
                      </div>
                      <span
                        className={cn(
                          'rounded-md px-3 py-2 text-xs font-medium',
                          row.actionClassName,
                        )}
                      >
                        {row.action}
                      </span>
                    </FrameCard>
                  );
                })}
              </FrameView>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
