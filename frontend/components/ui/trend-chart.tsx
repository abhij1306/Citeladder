import { cn } from '@/lib/utils';

export type TrendPoint = {
  label: string;
  /** Null is unavailable and renders as a gap, never as zero. */
  value: number | null;
  versionChange?: { note: string } | null;
};

const toLinePath = (segment: { x: number; y: number }[]) =>
  segment
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(1)},${point.y.toFixed(1)}`)
    .join(' ');

const valueText = (value: number | null) => (value === null ? 'unavailable' : `${value}`);

/** Token-only chart for cross-run visibility trends. */
export function TrendChart({
  data,
  width = 320,
  height = 120,
  label,
  className,
  domainMax = 100,
}: Readonly<{
  data: TrendPoint[];
  width?: number;
  height?: number;
  label?: string;
  className?: string;
  domainMax?: number;
}>) {
  const padding = 8;
  const innerWidth = width - padding * 2;
  const innerHeight = height - padding * 2;
  const effectiveDomainMax = domainMax > 0 ? domainMax : 100;
  const clamp = (value: number) => Math.max(0, Math.min(effectiveDomainMax, value));
  const stepX = data.length > 1 ? innerWidth / (data.length - 1) : 0;

  // Labels are NOT identities: a series can hold several points that format to
  // the same label (two runs on the same day both render "1 Aug"), which made
  // React collapse them onto one key. EVERY point carries its occurrence
  // suffix, including the first: suffixing only repeats left the bare label in
  // play, so a series holding both "1 Aug" and a literal "1 Aug#1" collided on
  // the second "1 Aug". With the suffix always present, a key splits uniquely
  // at its last `#` into (label, occurrence), and points keep a stable identity
  // across updates.
  const labelOccurrences = new Map<string, number>();
  const pointKeys = data.map((entry) => {
    const seen = labelOccurrences.get(entry.label) ?? 0;
    labelOccurrences.set(entry.label, seen + 1);
    return `${entry.label}#${seen}`;
  });

  const points = data.map((entry, index) => ({
    x: data.length > 1 ? padding + index * stepX : width / 2,
    y:
      entry.value === null
        ? null
        : padding + innerHeight * (1 - clamp(entry.value) / effectiveDomainMax),
  }));

  const segments: { x: number; y: number }[][] = [];
  let current: { x: number; y: number }[] = [];
  for (const point of points) {
    if (point.y === null) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push({ x: point.x, y: point.y });
    }
  }
  if (current.length) segments.push(current);
  const lineSegments = segments.filter((segment) => segment.length > 1);

  const summary = !data.length
    ? 'No trend data'
    : data.length === 1
      ? `Single point ${data[0].label} (${valueText(data[0].value)})`
      : `Trend from ${data[0].label} (${valueText(data[0].value)}) to ${data.at(-1)?.label} (${valueText(data.at(-1)?.value ?? null)})`;
  const gapNote = data.some((entry) => entry.value === null)
    ? ' Some points are unavailable and shown as gaps.'
    : '';
  const ariaLabel = label ? `${label}: ${summary}${gapNote}` : `${summary}${gapNote}`;

  return (
    <svg
      // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- SVG is the semantic image; an img cannot render this generated chart.
      role="img"
      aria-label={ariaLabel}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn('overflow-visible', className)}
    >
      <title>{ariaLabel}</title>
      {lineSegments.map((segment, index) => (
        <path
          key={`line-${index}`}
          d={toLinePath(segment)}
          fill="none"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="stroke-accent"
        />
      ))}
      {points.map((point, index) =>
        data[index].versionChange ? (
          <g key={`marker-${pointKeys[index]}`} data-version-marker="">
            <line
              x1={point.x}
              y1={padding}
              x2={point.x}
              y2={height - padding}
              strokeWidth={1}
              strokeDasharray="4 3"
              className="stroke-warning opacity-60"
              aria-hidden
            />
            <circle cx={point.x} cy={padding} r={3} className="fill-warning">
              <title>{`Version change at ${data[index].label}: ${data[index].versionChange?.note}`}</title>
            </circle>
          </g>
        ) : null,
      )}
      {points.map((point, index) =>
        point.y === null ? null : (
          <circle
            key={`point-${pointKeys[index]}`}
            cx={point.x}
            cy={point.y}
            r={2.5}
            className="fill-accent"
          >
            <title>{`${data[index].label}: ${data[index].value}`}</title>
          </circle>
        ),
      )}
    </svg>
  );
}
