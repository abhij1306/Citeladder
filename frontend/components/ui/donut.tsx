import type { CSSProperties } from 'react';

import { UnavailableValue } from '@/components/ui/unavailable-value';
import { cn } from '@/lib/utils';

export type DonutSegment = {
  label: string;
  value: number;
  /**
   * Bridged token stroke utility for this segment (e.g. 'stroke-citation-owned',
   * 'stroke-accent'). Token-only — callers never pass raw hex.
   */
  colorClass: string;
};

/**
 * Donut (§8) — segmented ring for per-engine / citation-share breakdowns.
 * Renders an SVG with one arc per segment plus a legend column. The whole
 * figure carries an ARIA label summarising the shares (role="img"), and every
 * legend row states its own percentage, so share is never colour-alone.
 *
 * A 14px ring on a --bg-well track, the value as a mono centre with a muted
 * caption beneath, and the legend as a right-hand column of dot + label + mono
 * value.
 *
 * Segments thicken on hover (v2): the arc grows 3px outward from its centre
 * line, which reads as the slice lifting without shifting the ring's geometry
 * or reflowing the legend. Purely decorative feedback — the legend already
 * states every share in text, and the effect is dropped under
 * `prefers-reduced-motion`.
 */
export function Donut({
  segments,
  size = 120,
  strokeWidth = 14,
  label,
  showLegend = true,
  centerLabel,
  centerCaption,
  className,
}: Readonly<{
  segments: DonutSegment[];
  size?: number;
  strokeWidth?: number;
  label?: string;
  showLegend?: boolean;
  centerLabel?: string;
  /** Small muted caption under the centre value (e.g. "of answers"). */
  centerCaption?: string;
  className?: string;
}>) {
  const total = segments.reduce((sum, s) => sum + Math.max(0, s.value), 0);
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  const summary =
    total > 0
      ? segments.map((s) => `${s.label} ${Math.round((s.value / total) * 100)}%`).join(', ')
      : 'No data';
  const ariaLabel = label ? `${label}: ${summary}` : summary;

  let offsetAccumulator = 0;

  return (
    <div className={cn('flex items-center gap-4', className)}>
      <div
        className="relative inline-flex items-center justify-center"
        style={{ width: size, height: size }}
      >
        <svg
          // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- SVG is the semantic image; img cannot render this generated donut.
          role="img"
          aria-label={ariaLabel}
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          className="-rotate-90"
        >
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            strokeWidth={strokeWidth}
            className="stroke-well"
          />
          {total > 0 &&
            segments.map((segment) => {
              const fraction = Math.max(0, segment.value) / total;
              const dash = fraction * circumference;
              const gap = circumference - dash;
              const dashOffset = -offsetAccumulator * circumference;
              offsetAccumulator += fraction;
              return (
                <circle
                  key={segment.label}
                  cx={size / 2}
                  cy={size / 2}
                  r={radius}
                  fill="none"
                  strokeWidth={strokeWidth}
                  strokeDasharray={`${dash} ${gap}`}
                  strokeDashoffset={dashOffset}
                  className={cn(
                    segment.colorClass,
                    // `motion-safe:hover:` — under prefers-reduced-motion the
                    // thickening is dropped outright, not merely un-transitioned
                    // (an untransitioned jump is the motion, instantly).
                    'origin-center transition-[stroke-width] duration-150 ease-out motion-safe:hover:[stroke-width:calc(var(--donut-stroke)+3px)] motion-reduce:transition-none',
                  )}
                  style={{ '--donut-stroke': `${strokeWidth}px` } as CSSProperties}
                />
              );
            })}
        </svg>
        {centerLabel ? (
          <span
            aria-hidden
            className="absolute inset-0 flex flex-col items-center justify-center gap-0.5"
          >
            <span className="mono text-foreground text-xl font-medium">{centerLabel}</span>
            {centerCaption ? <span className="text-muted text-xs">{centerCaption}</span> : null}
          </span>
        ) : null}
      </div>
      {showLegend ? (
        <ul className="flex flex-1 flex-col gap-2">
          {segments.map((segment) => (
            <li key={segment.label} className="flex items-center gap-2 text-xs">
              <svg aria-hidden width={8} height={8} viewBox="0 0 8 8" className="shrink-0">
                {/* Swatch reuses the segment's bridged stroke token (no raw hex,
                    and no runtime class string that Tailwind can't detect). */}
                {/* Drawn as a stroked ring with r = half the stroke width so it
                    reads as a solid dot while still honouring the caller's
                    `stroke-*` token (fill-* would need a second contract). */}
                <circle
                  cx={4}
                  cy={4}
                  r={2}
                  fill="none"
                  strokeWidth={4}
                  className={segment.colorClass}
                />
              </svg>
              <span className="text-secondary flex-1 truncate">{segment.label}</span>
              <span className="mono text-foreground font-medium">
                {total > 0 ? (
                  `${Math.round((segment.value / total) * 100)}%`
                ) : (
                  <UnavailableValue state="not_applicable" />
                )}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
