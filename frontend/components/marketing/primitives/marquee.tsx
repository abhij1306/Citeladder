import type { CSSProperties, ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * Marquee — a smooth, seamless, infinite horizontal strip.
 *
 * The caller passes the items ONCE; this renders `copies` of them and the CSS
 * translates the track by the width of exactly one copy, so at the loop point
 * copy 2 sits where copy 1 began and the restart cannot be seen.
 *
 * `copies` defaults to 4 rather than 2 on purpose. Two copies only look
 * seamless if a single copy already overflows the viewport; a short strip
 * (six chips, say) would run out of content and visibly empty before looping.
 * Four guarantees overflow at any realistic width for the lists used here.
 *
 * Every copy after the first is `aria-hidden`, so assistive tech reads the
 * list once. Motion pauses on hover, and under `prefers-reduced-motion` the
 * track stops at its start and becomes a plain horizontal scroll region — the
 * items stay reachable either way.
 *
 * `speed` is seconds per full cycle (one copy's width). Longer lists need a
 * longer duration to hold the apparent pixel rate steady.
 */
export function Marquee({
  children,
  direction = 'left',
  speed = 42,
  copies = 4,
  label,
  className,
}: Readonly<{
  children: ReactNode;
  /** `left` scrolls content leftward; `right` scrolls it rightward. */
  direction?: 'left' | 'right';
  /** Seconds per full cycle. */
  speed?: number;
  /** How many times the list is repeated; must overflow the viewport. */
  copies?: number;
  /** Accessible name for the strip as a whole. */
  label: string;
  className?: string;
}>) {
  return (
    <div
      className={cn('citeladder-marquee relative w-full overflow-hidden', className)}
      role="group"
      aria-label={label}
    >
      <div
        className="citeladder-marquee-track"
        data-direction={direction === 'right' ? 'reverse' : undefined}
        style={
          {
            '--citeladder-marquee-duration': `${speed}s`,
            // One copy as a fraction of the whole track — the exact distance
            // the keyframe travels.
            '--citeladder-marquee-copy': `${100 / copies}%`,
          } as CSSProperties
        }
      >
        {Array.from({ length: copies }, (_, copy) => (
          <div
            key={copy}
            className="flex shrink-0 items-center"
            aria-hidden={copy > 0 ? true : undefined}
          >
            {children}
          </div>
        ))}
      </div>
    </div>
  );
}
