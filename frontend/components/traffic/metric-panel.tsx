'use client';

import { useEffect, useId, useRef, useState } from 'react';

import type { TrendPoint } from '@/components/ui/trend-chart';
import { cn } from '@/lib/utils';

/**
 * One small-multiple panel: a single metric on its OWN zero-based, labelled
 * y-axis.
 *
 * Why a panel per metric rather than four series on one plot: Traffic mixes
 * three unit types — counts (clicks, impressions), a percentage (CTR) and a
 * rank (position). On a shared plot they cannot share a scale, and the
 * previous implementation resolved that by normalising each series to its own
 * min/max, which made every line span the full plot height. Clicks (0–8) and
 * impressions (0–346) drew with identical amplitude, the gridlines matched no
 * scale at all, and a flat series collapsed onto the baseline as if it were
 * zero. A second y-axis would only trade that for an arbitrary alignment
 * between the two scales, which invents a correlation the data does not have.
 *
 * Each panel is therefore self-contained: its own domain from 0, its own
 * ticks, one series. One series needs no legend — the panel title names it.
 */

const PLOT = {
  /** Fallback until the container is measured (SSR / first paint). */
  fallbackWidth: 320,
  height: 148,
  left: 36,
  right: 10,
  top: 10,
  bottom: 24,
} as const;

const INNER_HEIGHT = PLOT.height - PLOT.top - PLOT.bottom;

/**
 * The panel's rendered pixel width.
 *
 * The plot is drawn at TRUE pixel size rather than scaled from a fixed
 * viewBox: panels are laid out to fill the row, so a single active metric is
 * four times as wide as one of four. A fixed viewBox would either letterbox
 * (uniform scaling leaves blank space) or stretch the stroke widths and tick
 * text along with the geometry. Measuring keeps 2px lines 2px wide and the
 * axis text one size in every layout.
 */
function useMeasuredWidth() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState<number>(PLOT.fallbackWidth);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    // jsdom and older browsers have no ResizeObserver; the fallback width
    // keeps the chart renderable rather than collapsing it to nothing.
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      const next = entry?.contentRect.width ?? 0;
      if (next > 0) setWidth(next);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return { ref, width };
}
/** Tick ratios from the top of the domain down to zero. */
const TICK_RATIOS = [1, 0.75, 0.5, 0.25, 0] as const;

export type MetricPanelSeries = {
  /** Tailwind classes bridged off the --chart-N tokens (never a raw hex). */
  strokeClass: string;
  fillClass: string;
};

type PlottedPoint = { x: number; y: number; value: number; label: string };

function toSegments(points: (PlottedPoint | null)[]): PlottedPoint[][] {
  const segments: PlottedPoint[][] = [];
  let current: PlottedPoint[] = [];
  for (const point of points) {
    if (point === null) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push(point);
    }
  }
  if (current.length) segments.push(current);
  return segments;
}

const toPath = (segment: PlottedPoint[]) =>
  segment.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');

export function MetricPanel({
  title,
  description,
  points,
  domainMax,
  formatTick,
  formatValue,
  series,
  invert = false,
  className,
  testId,
}: Readonly<{
  title: string;
  description?: string;
  points: TrendPoint[];
  /** Top of the domain. The bottom is ALWAYS zero — never a floating baseline. */
  domainMax: number;
  formatTick: (value: number) => string;
  formatValue: (value: number) => string;
  series: MetricPanelSeries;
  /**
   * Rank metrics (average position) improve as they FALL, so their axis runs
   * best-at-the-top. Without this the line rises when rankings get worse.
   */
  invert?: boolean;
  className?: string;
  testId?: string;
}>) {
  const clipId = useId();
  const [hover, setHover] = useState<PlottedPoint | null>(null);
  const { ref, width } = useMeasuredWidth();

  const plotWidth = Math.max(width, 160);
  const innerWidth = plotWidth - PLOT.left - PLOT.right;
  const safeMax = domainMax > 0 ? domainMax : 1;
  const stepX = points.length > 1 ? innerWidth / (points.length - 1) : 0;

  const plotted: (PlottedPoint | null)[] = points.map((point, index) => {
    if (point.value === null) return null;
    const clamped = Math.max(0, Math.min(safeMax, point.value));
    const ratio = clamped / safeMax;
    return {
      x: points.length > 1 ? PLOT.left + index * stepX : PLOT.left + innerWidth / 2,
      y: PLOT.top + INNER_HEIGHT * (invert ? ratio : 1 - ratio),
      value: point.value,
      label: point.label,
    };
  });

  const segments = toSegments(plotted).filter((segment) => segment.length > 1);
  const drawn = plotted.filter((p): p is PlottedPoint => p !== null);
  const lone = drawn.length === 1 ? drawn[0] : null;

  const first = points[0]?.label ?? '';
  const last = points.at(-1)?.label ?? '';
  const middle = points.length > 2 ? points[Math.floor((points.length - 1) / 2)].label : '';

  const summary = drawn.length
    ? `${title}: ${formatValue(drawn[0].value)} on ${drawn[0].label} to ${formatValue(
        drawn.at(-1)!.value,
      )} on ${drawn.at(-1)!.label}${
        drawn.length < points.length ? '. Some buckets are unavailable and shown as gaps.' : ''
      }`
    : `${title}: no data in this window`;

  return (
    <figure className={cn('grid gap-1', className)} data-testid={testId}>
      <figcaption className="grid gap-0.5">
        <span className="text-foreground text-xs font-semibold">{title}</span>
        {description ? <span className="text-muted text-2xs">{description}</span> : null}
      </figcaption>

      <div ref={ref} className="relative">
        <svg
          role="img"
          aria-label={summary}
          viewBox={`0 0 ${plotWidth} ${PLOT.height}`}
          width={plotWidth}
          height={PLOT.height}
          className="h-[148px] w-full"
          onMouseLeave={() => setHover(null)}
        >
          <title>{summary}</title>
          <defs>
            <clipPath id={clipId}>
              <rect x={PLOT.left} y={PLOT.top} width={innerWidth} height={INNER_HEIGHT} />
            </clipPath>
          </defs>

          {TICK_RATIOS.map((ratio) => {
            const value = safeMax * ratio;
            const y = PLOT.top + INNER_HEIGHT * (invert ? ratio : 1 - ratio);
            return (
              <g key={ratio}>
                <line
                  x1={PLOT.left}
                  y1={y}
                  x2={plotWidth - PLOT.right}
                  y2={y}
                  strokeWidth={1}
                  className="stroke-border-subtle"
                />
                <text
                  x={PLOT.left - 6}
                  y={y + 3}
                  textAnchor="end"
                  className="fill-muted text-3xs tabular-nums"
                >
                  {formatTick(value)}
                </text>
              </g>
            );
          })}

          <g clipPath={`url(#${clipId})`}>
            {segments.map((segment) => (
              <path
                key={`${segment[0].label}-${segment.length}`}
                d={toPath(segment)}
                fill="none"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                className={series.strokeClass}
              />
            ))}
            {/* A lone reading has no line to draw, so mark it or the panel
                would read as empty. */}
            {lone ? <circle cx={lone.x} cy={lone.y} r={3} className={series.fillClass} /> : null}
          </g>

          {hover ? (
            <g aria-hidden>
              <line
                x1={hover.x}
                y1={PLOT.top}
                x2={hover.x}
                y2={PLOT.top + INNER_HEIGHT}
                strokeWidth={1}
                className="stroke-border"
              />
              <circle
                cx={hover.x}
                cy={hover.y}
                r={4}
                strokeWidth={2}
                className={cn(series.fillClass, 'stroke-panel')}
              />
            </g>
          ) : null}

          {/* Full-height hit targets: bigger than the marks, so a value is
              readable without pixel-hunting a 2px line. */}
          {drawn.map((point) => (
            <rect
              key={`hit-${point.label}`}
              x={point.x - Math.max(stepX, 8) / 2}
              y={PLOT.top}
              width={Math.max(stepX, 8)}
              height={INNER_HEIGHT}
              fill="transparent"
              onMouseEnter={() => setHover(point)}
            />
          ))}

          <text x={PLOT.left} y={PLOT.height - 6} className="fill-muted text-3xs">
            {first}
          </text>
          {middle ? (
            <text
              x={PLOT.left + innerWidth / 2}
              y={PLOT.height - 6}
              textAnchor="middle"
              className="fill-muted text-3xs"
            >
              {middle}
            </text>
          ) : null}
          {last && last !== first ? (
            <text
              x={plotWidth - PLOT.right}
              y={PLOT.height - 6}
              textAnchor="end"
              className="fill-muted text-3xs"
            >
              {last}
            </text>
          ) : null}
        </svg>

        {hover ? (
          <div
            role="status"
            className="border-border-subtle bg-elevated text-foreground text-2xs shadow-card pointer-events-none absolute top-0 rounded-md border px-2 py-1"
            style={{ left: `${(hover.x / plotWidth) * 100}%` }}
          >
            <span className="text-muted">{hover.label}</span>{' '}
            <span className="font-mono font-semibold tabular-nums">{formatValue(hover.value)}</span>
          </div>
        ) : null}
      </div>
    </figure>
  );
}
