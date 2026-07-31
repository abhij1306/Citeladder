'use client';

import { useRef, useState } from 'react';
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
import { ExampleDataNote } from './wallpaper-panel';

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
    productSolution: 'Turn visibility gaps into prioritized, high-ROI content & schema updates',
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
    '“For enterprise analytics, teams most often cite Searchify alongside market leaders for its verifiable citation tracking…”',
  chain: [
    ['Provider', 'ChatGPT 4.5'],
    ['Artifact', 'a3f9c1'],
    ['Analyzer', 'visibility-v4.2'],
    ['Reproducible', 'yes'],
  ],
} as const;

/**
 * Compact, Authentic Searchify Product Showcase Canvas with Real Trend Graphs.
 * Fits comfortably on screen with streamlined sidebar, real-time SVG charts,
 * and a narrative tour connecting "The Shift" to "How Searchify Helps You Win".
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
    <div ref={containerRef} className="mkt-snapshot mx-auto max-w-5xl p-3 sm:p-4">
      {/* Storytelling Tour Stepper */}
      <div className="bg-mkt-paper-raised border-mkt-line-soft mb-4 rounded-lg border p-3 sm:p-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <TourStepper
            steps={STORY_STEPS}
            activeStep={activeStep}
            isPlaying={isPlaying}
            onSelectStep={selectStep}
            onTogglePlay={togglePlay}
            compact
          />
          <div className="hidden sm:block">
            <ExampleDataNote />
          </div>
        </div>

        <div className="border-mkt-line-soft/60 text-mkt-meta mt-3 flex items-center justify-between border-t pt-2">
          <div className="flex items-center gap-2 truncate">
            <span className="bg-mkt-evidence size-1.5 shrink-0 animate-pulse rounded-full" />
            <span className="text-mkt-proof font-mono font-semibold uppercase">
              {currentStep.label.split('.')[1]?.trim()}:
            </span>
            <span className="text-mkt-ink-muted truncate font-medium">
              {currentStep.productSolution} — every score opens to the answer behind it.
            </span>
          </div>
          <div className="ml-2 shrink-0 sm:hidden">
            <ExampleDataNote />
          </div>
        </div>
      </div>

      {/* Compact Product Layout Canvas */}
      <div
        aria-hidden
        className="mkt-snapshot-canvas bg-mkt-paper-raised grid min-h-[280px] items-stretch gap-0 overflow-hidden lg:grid-cols-[12rem_minmax(0,1fr)]"
      >
        {/* Streamlined Authentic Sidebar */}
        <aside className="bg-mkt-surface border-mkt-line-soft hidden flex-col justify-between border-r p-3 lg:flex">
          <div className="space-y-4">
            {COMPACT_NAV_GROUPS.map((group) => (
              <div key={group.title} className="space-y-0.5">
                <p className="text-mkt-meta text-mkt-ink-muted mb-1 px-2 font-mono font-bold uppercase">
                  {group.title}
                </p>
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const isActive = item.label === currentStep.navLabel;

                  return (
                    <div
                      key={item.label}
                      className={`text-mkt-meta relative flex items-center gap-2 rounded-md px-2 py-1.5 font-medium transition-colors ${
                        isActive
                          ? 'bg-mkt-proof-soft text-mkt-proof font-semibold'
                          : 'text-mkt-ink-muted'
                      }`}
                    >
                      {isActive && (
                        <span className="bg-mkt-proof absolute top-1 bottom-1 left-0 w-0.5 rounded-r-xs" />
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
        <div className="bg-mkt-surface flex flex-col justify-between p-4 sm:p-5">
          <AnimatePresence mode="wait">
            {activeStep === 0 && (
              <m.div
                key="observe-view"
                initial={reduceMotion ? false : { opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduceMotion ? undefined : { opacity: 0, y: -6 }}
                transition={{ duration: 0.25, ease: EASE_OUT }}
                className="space-y-4"
              >
                <div className="flex items-center justify-between">
                  <p className="font-mkt-display text-mkt-sm text-mkt-ink font-semibold">
                    Visibility Overview & Trend Graph
                  </p>
                  <span className="text-mkt-meta text-mkt-proof flex items-center gap-1 font-mono font-semibold">
                    <TrendingUp className="size-3" /> Cross-Run Trend
                  </span>
                </div>

                {/* Metrics Row */}
                <div
                  className={cn(
                    'border-mkt-line-soft bg-mkt-surface grid rounded-md border',
                    GRID_COLS_MAP[METRICS.length] ?? 'grid-cols-3',
                  )}
                >
                  {METRICS.map((metric, index) => (
                    <div
                      key={metric.label}
                      className={`p-3 sm:p-3 ${
                        index < METRICS.length - 1 ? 'border-mkt-line-soft border-r' : ''
                      }`}
                    >
                      <Meta as="p" className="text-mkt-meta text-mkt-ink-muted">
                        {metric.label}
                      </Meta>
                      <b className="text-mkt-body text-mkt-ink mt-0.5 block font-mono leading-none font-bold tabular-nums">
                        <AnimatedNumber value={metric.value} />
                        {'delta' in metric && metric.delta && (
                          <small className="text-mkt-meta text-mkt-evidence-text ml-1 font-mono font-semibold tabular-nums">
                            {metric.delta}
                          </small>
                        )}
                      </b>
                    </div>
                  ))}
                </div>

                {/* SVG Trend Graph (Real Product Chart) */}
                <div className="bg-mkt-paper-raised border-mkt-line-soft rounded-md border p-3">
                  <div className="text-mkt-meta text-mkt-ink-muted mb-2 flex items-center justify-between font-mono">
                    <span>Visibility Score Trend (Last 8 Audits)</span>
                    <span className="text-mkt-evidence-text font-semibold">72.4% Peak</span>
                  </div>
                  <div className="relative flex h-20 w-full items-end pt-2">
                    {/* SVG Curve Line */}
                    <svg
                      className="h-full w-full overflow-visible"
                      viewBox="0 0 300 60"
                      preserveAspectRatio="none"
                    >
                      <defs>
                        <linearGradient id="visibilityGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop
                            offset="0%"
                            stopColor="var(--color-mkt-accent)"
                            stopOpacity="0.25"
                          />
                          <stop
                            offset="100%"
                            stopColor="var(--color-mkt-accent)"
                            stopOpacity="0.0"
                          />
                        </linearGradient>
                      </defs>
                      <path
                        d="M 0,45 Q 40,38 80,32 T 160,22 T 240,15 T 300,8 L 300,60 L 0,60 Z"
                        fill="url(#visibilityGradient)"
                      />
                      <path
                        d="M 0,45 Q 40,38 80,32 T 160,22 T 240,15 T 300,8"
                        fill="none"
                        stroke="var(--color-mkt-accent)"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                      />
                      <circle cx="300" cy="8" r="3.5" fill="var(--color-mkt-accent)" />
                    </svg>
                  </div>
                  <div className="text-mkt-meta text-mkt-ink-muted border-mkt-line-soft mt-1.5 flex justify-between border-t pt-1 font-mono">
                    <span>Apr 01</span>
                    <span>May 15</span>
                    <span>Jun 30 (Latest Run)</span>
                  </div>
                </div>
              </m.div>
            )}

            {activeStep === 1 && (
              <m.div
                key="trace-view"
                initial={reduceMotion ? false : { opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduceMotion ? undefined : { opacity: 0, y: -6 }}
                transition={{ duration: 0.25, ease: EASE_OUT }}
                className="space-y-3"
              >
                <div className="flex items-center justify-between">
                  <p className="font-mkt-display text-mkt-sm text-mkt-ink font-semibold">
                    Answers & Evidence Trace
                  </p>
                  <span className="text-mkt-meta text-mkt-proof flex items-center gap-1 font-mono font-semibold">
                    <ShieldCheck className="text-mkt-evidence-text size-3" /> 100% Verifiable
                  </span>
                </div>

                <div className="bg-mkt-paper-raised border-mkt-line-soft rounded-md border p-3">
                  <div className="text-mkt-meta text-mkt-ink-muted flex items-center justify-between">
                    <span className="text-mkt-ink flex items-center gap-1 font-semibold">
                      <Search className="text-mkt-proof size-3" />
                      Observed Answer Text
                    </span>
                    <span className="text-mkt-proof font-mono font-semibold tabular-nums">
                      Visibility score: <AnimatedNumber value="72.4" />
                    </span>
                  </div>

                  <p className="text-mkt-meta text-mkt-ink mt-2 leading-relaxed font-medium">
                    {EVIDENCE.answer}
                  </p>

                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {EVIDENCE.chain.map(([label, value]) => (
                      <span
                        key={label}
                        className="text-mkt-meta bg-mkt-surface border-mkt-line text-mkt-evidence-text rounded-full border px-2 py-0.5 font-mono"
                      >
                        <span className="text-mkt-ink-muted uppercase">{label}:</span>{' '}
                        <span className="font-semibold">{value}</span>
                      </span>
                    ))}
                  </div>
                </div>
              </m.div>
            )}

            {activeStep === 2 && (
              <m.div
                key="benchmark-view"
                initial={reduceMotion ? false : { opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduceMotion ? undefined : { opacity: 0, y: -6 }}
                transition={{ duration: 0.25, ease: EASE_OUT }}
                className="space-y-3"
              >
                <div className="flex items-center justify-between">
                  <p className="font-mkt-display text-mkt-sm text-mkt-ink font-semibold">
                    Share of Voice & Competitive Chart
                  </p>
                  <span className="text-mkt-meta text-mkt-proof font-mono font-semibold">
                    Market Share Comparison
                  </span>
                </div>

                <div className="bg-mkt-paper-raised border-mkt-line-soft space-y-3 rounded-md border p-3">
                  <div>
                    <div className="text-mkt-meta mb-1 flex justify-between font-semibold">
                      <span className="text-mkt-ink">Acme Corp (Your Brand)</span>
                      <span className="text-mkt-accent font-mono">38.4% Share (#1 Lead)</span>
                    </div>
                    <div className="bg-mkt-line-soft h-2 w-full overflow-hidden rounded-full">
                      <div className="bg-mkt-accent h-full w-[38.4%] rounded-full" />
                    </div>
                  </div>

                  <div>
                    <div className="text-mkt-meta text-mkt-ink-soft mb-1 flex justify-between">
                      <span>Competitor A</span>
                      <span className="font-mono">28.1%</span>
                    </div>
                    <div className="bg-mkt-line-soft h-2 w-full overflow-hidden rounded-full">
                      <div className="bg-mkt-line-strong h-full w-[28.1%] rounded-full opacity-60" />
                    </div>
                  </div>

                  <div>
                    <div className="text-mkt-meta text-mkt-ink-soft mb-1 flex justify-between">
                      <span>Competitor B</span>
                      <span className="font-mono">19.5%</span>
                    </div>
                    <div className="bg-mkt-line-soft h-2 w-full overflow-hidden rounded-full">
                      <div className="bg-mkt-line-strong h-full w-[19.5%] rounded-full opacity-40" />
                    </div>
                  </div>
                </div>
              </m.div>
            )}

            {activeStep === 3 && (
              <m.div
                key="optimize-view"
                initial={reduceMotion ? false : { opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduceMotion ? undefined : { opacity: 0, y: -6 }}
                transition={{ duration: 0.25, ease: EASE_OUT }}
                className="space-y-3"
              >
                <div className="flex items-center justify-between">
                  <p className="font-mkt-display text-mkt-sm text-mkt-ink font-semibold">
                    Opportunities & Action Recommendations
                  </p>
                  <span className="text-mkt-meta text-mkt-proof font-mono font-semibold">
                    High-Impact Moves
                  </span>
                </div>

                <div className="bg-mkt-paper-raised border-mkt-line-soft flex items-center justify-between rounded-md border p-3">
                  <div className="flex items-center gap-2">
                    <span className="bg-mkt-amber-soft text-mkt-amber-text border-mkt-amber-line/50 rounded-md border p-1">
                      <Zap className="size-3" />
                    </span>
                    <div>
                      <span className="text-mkt-meta text-mkt-ink block font-semibold">
                        Update Deprecated Docs Cited by ChatGPT
                      </span>
                      <span className="text-mkt-meta text-mkt-ink-muted">
                        Increases ChatGPT recommendation score by +14%
                      </span>
                    </div>
                  </div>
                  <span className="text-mkt-meta bg-mkt-accent rounded-md px-2 py-0.5 font-semibold text-white">
                    Fix Now
                  </span>
                </div>

                <div className="bg-mkt-paper-raised border-mkt-line-soft flex items-center justify-between rounded-md border p-3">
                  <div className="flex items-center gap-2">
                    <span className="bg-mkt-proof-soft text-mkt-proof border-mkt-proof-line/50 rounded-md border p-1">
                      <Bot className="size-3" />
                    </span>
                    <div>
                      <span className="text-mkt-meta text-mkt-ink block font-semibold">
                        Publish Enterprise Comparison Table for Gemini
                      </span>
                      <span className="text-mkt-meta text-mkt-ink-muted">
                        Captures missing citations in enterprise buyer queries
                      </span>
                    </div>
                  </div>
                  <span className="text-mkt-meta bg-mkt-surface border-mkt-line text-mkt-ink rounded-md border px-2 py-0.5 font-semibold">
                    View Draft
                  </span>
                </div>
              </m.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
