'use client';

import { useEffect, useState } from 'react';

import { cn } from '@/lib/utils';
import { scoreBand, scoreBandFill } from './score-band';

/** Token-only horizontal score meter with the same motion contract as ScoreRing. */
export function ScoreBar({
  value,
  label,
  className,
}: Readonly<{ value: number; label?: string; className?: string }>) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  const [swept, setSwept] = useState(false);

  useEffect(() => {
    const frame = requestAnimationFrame(() => setSwept(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <div className={className}>
      <meter
        className="sr-only"
        aria-label={label ?? `Score: ${clamped} out of 100`}
        min={0}
        max={100}
        value={clamped}
      />
      <div aria-hidden className="bg-active h-2 w-full overflow-hidden rounded-full">
        <div
          className={cn(
            'h-full rounded-full transition-[width] duration-[800ms] ease-out motion-reduce:transition-none',
            scoreBandFill[scoreBand(clamped)],
          )}
          style={{ width: swept ? `${clamped}%` : 0 }}
        />
      </div>
    </div>
  );
}
