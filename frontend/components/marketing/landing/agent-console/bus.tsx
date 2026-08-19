import { cn } from '@/lib/utils';

/**
 * The converging bus. Three straight runs leave the rows, the outer two bend
 * into the centre line, and one trunk carries the merged stream into the agent.
 *
 * The viewBox is 192x480 and the element is 16% x 100% of a 1200x480 stage (the
 * 5:2 ratio above), so the ratio matches exactly and nothing is stretched — the
 * dots stay round. Every y here is the former 600-tall geometry scaled by 0.8;
 * the corner radius stays 24 because a scaled arc would no longer be circular.
 * The `pipeline-stream` class is what globals.css uses to hide SMIL dots under
 * `prefers-reduced-motion`.
 */
const BUS_ROUTES = [
  'M 0 80 H 60 A 24 24 0 0 1 84 104 V 216 A 24 24 0 0 0 108 240 H 186',
  'M 0 240 H 186',
  'M 0 400 H 60 A 24 24 0 0 0 84 376 V 264 A 24 24 0 0 1 108 240 H 186',
] as const;
// Constant dot speed, so the bent routes simply take longer to arrive.
const BUS_DURATIONS = [3, 1.55, 3] as const;

export function Bus({ active, reduce }: Readonly<{ active: number; reduce: boolean }>) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 192 480"
      fill="none"
      className="pipeline-stream absolute inset-y-0 left-[30%] hidden h-full w-[16%] xl:block"
    >
      {BUS_ROUTES.map((d, index) => (
        <g key={d}>
          <path
            d={d}
            strokeWidth={index === active ? 2 : 1.25}
            strokeDasharray="4 5"
            className={cn(
              'transition-[stroke,stroke-width] duration-500',
              index === active ? 'stroke-accent' : 'stroke-border-strong',
            )}
          />
          {[0, 1, 2].map((slot) => (
            <circle
              key={slot}
              r={index === active ? 3 : 2}
              className={cn(
                'fill-accent transition-opacity duration-500',
                index === active ? 'opacity-100' : 'opacity-30',
              )}
            >
              <animateMotion
                path={d}
                dur={`${BUS_DURATIONS[index]}s`}
                begin={`${(slot * (BUS_DURATIONS[index] ?? 3)) / 3}s`}
                repeatCount="indefinite"
              />
            </circle>
          ))}
        </g>
      ))}

      {/* The merged trunk, drawn solid over the dashed routes it carries. Its
          y is the stage centre — 240 in the 480-tall box, matching the routes. */}
      <path d="M 108 240 H 186" className="stroke-accent" strokeWidth="2" />
      <polygon points="182,232 196,240 182,248" className="fill-accent" />
      <circle
        cx="108"
        cy="240"
        r="4"
        className={cn('fill-accent', !reduce && 'animate-pulse')}
        aria-hidden
      />
    </svg>
  );
}
