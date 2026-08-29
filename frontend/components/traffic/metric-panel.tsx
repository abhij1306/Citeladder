'use client';

import { useEffect, useId, useRef, useState } from 'react';

import type { TrendPoint } from '@/components/ui/trend-chart';
import { cn } from '@/lib/utils';

const PLOT = {
  fallbackWidth: 320,
  height: 148,
  left: 36,
  right: 10,
  top: 10,
  bottom: 24,
} as const;
const INNER_HEIGHT = PLOT.height - PLOT.top - PLOT.bottom;
const TICK_RATIOS = [1, 0.75, 0.5, 0.25, 0] as const;

type MetricPanelSeries = {
  /** Tailwind classes bridged off the --chart-N tokens (never a raw hex). */
  strokeClass: string;
  fillClass: string;
};

type PlottedPoint = { x: number; y: number; value: number; label: string };
type MetricPanelProps = Readonly<{
  title: string;
  description?: string;
  points: TrendPoint[];
  /** Top of the domain. The bottom is ALWAYS zero — never a floating baseline. */
  domainMax: number;
  formatTick: (value: number) => string;
  formatValue: (value: number) => string;
  series: MetricPanelSeries;
  /** Rank metrics improve as they fall, so their axis runs best-at-the-top. */
  invert?: boolean;
  className?: string;
  testId?: string;
}>;

/** Measure at rendered pixels, preserving line and text sizes at every panel width. */
function useMeasuredWidth() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState<number>(PLOT.fallbackWidth);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      const next = entry?.contentRect.width ?? 0;
      if (next > 0) setWidth(next);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return { ref, width };
}

function toSegments(points: (PlottedPoint | null)[]) {
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
  segment
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(1)},${point.y.toFixed(1)}`)
    .join(' ');

function createChartData(points: TrendPoint[], domainMax: number, width: number, invert: boolean) {
  const plotWidth = Math.max(width, 160);
  const innerWidth = plotWidth - PLOT.left - PLOT.right;
  const safeMax = domainMax > 0 ? domainMax : 1;
  const stepX = points.length > 1 ? innerWidth / (points.length - 1) : 0;
  const plotted = points.map((point, index) =>
    plotPoint(point, index, points.length, safeMax, stepX, innerWidth, invert),
  );
  const allSegments = toSegments(plotted);
  const segments = allSegments.filter((segment) => segment.length > 1);
  const isolatedPoints = allSegments.flatMap((segment) => (segment.length === 1 ? segment : []));
  const drawn = plotted.filter((point): point is PlottedPoint => point !== null);

  return { plotWidth, innerWidth, safeMax, stepX, segments, isolatedPoints, drawn };
}

function plotPoint(
  point: TrendPoint,
  index: number,
  pointCount: number,
  safeMax: number,
  stepX: number,
  innerWidth: number,
  invert: boolean,
): PlottedPoint | null {
  if (point.value === null) return null;
  const clamped = Math.max(0, Math.min(safeMax, point.value));
  const ratio = clamped / safeMax;
  return {
    x: pointCount > 1 ? PLOT.left + index * stepX : PLOT.left + innerWidth / 2,
    y: PLOT.top + INNER_HEIGHT * (invert ? ratio : 1 - ratio),
    value: point.value,
    label: point.label,
  };
}

function chartSummary(
  title: string,
  points: TrendPoint[],
  drawn: PlottedPoint[],
  formatValue: (value: number) => string,
) {
  if (!drawn.length) return `${title}: no data in this window`;
  const first = drawn[0];
  const last = drawn.at(-1)!;
  const gaps =
    drawn.length < points.length ? '. Some buckets are unavailable and shown as gaps.' : '';
  return `${title}: ${formatValue(first.value)} on ${first.label} to ${formatValue(last.value)} on ${last.label}${gaps}`;
}

/** One zero-based, labelled y-axis for a single traffic metric. */
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
}: MetricPanelProps) {
  const clipId = useId();
  const [hover, setHover] = useState<PlottedPoint | null>(null);
  const { ref, width } = useMeasuredWidth();
  const chart = createChartData(points, domainMax, width, invert);
  const summary = chartSummary(title, points, chart.drawn, formatValue);

  return (
    <figure className={cn('grid gap-1', className)} data-testid={testId}>
      <figcaption className="grid gap-0.5">
        <span className="text-foreground text-xs font-medium">{title}</span>
        {description ? <span className="text-muted text-2xs">{description}</span> : null}
      </figcaption>

      <div ref={ref} className="relative">
        {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- Pointer handlers reveal a visual tooltip; the SVG label exposes the full summary without interaction. */}
        <svg
          // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- SVG is the semantic image; img cannot render this generated interactive chart.
          role="img"
          aria-label={summary}
          viewBox={`0 0 ${chart.plotWidth} ${PLOT.height}`}
          width={chart.plotWidth}
          height={PLOT.height}
          className="h-37 w-full"
          onMouseLeave={() => setHover(null)}
        >
          <title>{summary}</title>
          <defs>
            <clipPath id={clipId}>
              <rect x={PLOT.left} y={PLOT.top} width={chart.innerWidth} height={INNER_HEIGHT} />
            </clipPath>
          </defs>
          <ChartYAxis
            plotWidth={chart.plotWidth}
            safeMax={chart.safeMax}
            invert={invert}
            formatTick={formatTick}
          />
          <g clipPath={`url(#${clipId})`}>
            {chart.segments.map((segment) => (
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
            {chart.isolatedPoints.map((point) => (
              <circle
                key={`isolated-${point.label}`}
                cx={point.x}
                cy={point.y}
                r={3}
                className={series.fillClass}
                data-isolated-point=""
              />
            ))}
          </g>
          {hover ? <HoverMarker point={hover} series={series} /> : null}
          <HitTargets points={chart.drawn} stepX={chart.stepX} onHover={setHover} />
          <ChartXAxis points={points} innerWidth={chart.innerWidth} plotWidth={chart.plotWidth} />
        </svg>
        {hover ? (
          <HoverTooltip point={hover} plotWidth={chart.plotWidth} formatValue={formatValue} />
        ) : null}
      </div>
    </figure>
  );
}

function ChartYAxis({
  plotWidth,
  safeMax,
  invert,
  formatTick,
}: Readonly<{
  plotWidth: number;
  safeMax: number;
  invert: boolean;
  formatTick: (value: number) => string;
}>) {
  return TICK_RATIOS.map((ratio) => {
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
  });
}

function HoverMarker({
  point,
  series,
}: Readonly<{ point: PlottedPoint; series: MetricPanelSeries }>) {
  return (
    <g aria-hidden>
      <line
        x1={point.x}
        y1={PLOT.top}
        x2={point.x}
        y2={PLOT.top + INNER_HEIGHT}
        strokeWidth={1}
        className="stroke-border"
      />
      <circle
        cx={point.x}
        cy={point.y}
        r={4}
        strokeWidth={2}
        className={cn(series.fillClass, 'stroke-panel')}
      />
    </g>
  );
}

function HitTargets({
  points,
  stepX,
  onHover,
}: Readonly<{
  points: PlottedPoint[];
  stepX: number;
  onHover: (point: PlottedPoint) => void;
}>) {
  return points.map((point) => (
    <rect
      key={`hit-${point.label}`}
      x={point.x - Math.max(stepX, 8) / 2}
      y={PLOT.top}
      width={Math.max(stepX, 8)}
      height={INNER_HEIGHT}
      fill="transparent"
      onMouseEnter={() => onHover(point)}
    />
  ));
}

function ChartXAxis({
  points,
  innerWidth,
  plotWidth,
}: Readonly<{
  points: TrendPoint[];
  innerWidth: number;
  plotWidth: number;
}>) {
  const first = points[0]?.label ?? '';
  const last = points.at(-1)?.label ?? '';
  const middle = points.length > 2 ? points[Math.floor((points.length - 1) / 2)].label : '';

  return (
    <>
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
    </>
  );
}

function HoverTooltip({
  point,
  plotWidth,
  formatValue,
}: Readonly<{
  point: PlottedPoint;
  plotWidth: number;
  formatValue: (value: number) => string;
}>) {
  return (
    <div
      aria-hidden="true"
      className="border-border-subtle bg-elevated text-foreground text-2xs shadow-card pointer-events-none absolute top-0 rounded-sm border px-2 py-1"
      style={{ left: `${(point.x / plotWidth) * 100}%` }}
    >
      <span className="text-muted">{point.label}</span>{' '}
      <span className="font-mono font-medium tabular-nums">{formatValue(point.value)}</span>
    </div>
  );
}
