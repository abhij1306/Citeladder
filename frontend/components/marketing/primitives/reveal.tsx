import type { ReactNode } from 'react';

type MotionChildren = Readonly<{ children: ReactNode; className?: string }>;
type Direction = 'up' | 'left' | 'right';

/**
 * Enhanced cross-browser scroll choreography for page content using GSAP ScrollTrigger.
 * Elements render fully visible in SSR HTML, and GSAP handles smooth scroll entrances
 * across all browsers (including Firefox, Safari, Chrome, Edge).
 */
export function Reveal({
  children,
  className,
  from = 'up',
}: MotionChildren & { from?: Direction }) {
  return (
    <div data-citeladder-reveal="" data-citeladder-reveal-from={from} className={className}>
      {children}
    </div>
  );
}

export function StaggerGroup({ children, className }: MotionChildren) {
  return (
    <div data-citeladder-reveal="stagger" className={className}>
      {children}
    </div>
  );
}

export function StaggerItem({ children, className }: MotionChildren) {
  return <div className={className}>{children}</div>;
}
