'use client';

import type { ReactNode } from 'react';
import { LazyMotion, MotionConfig } from 'motion/react';

const loadMotionFeatures = () => import('./motion-features').then((module) => module.default);

export function ProductMotionProvider({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <LazyMotion features={loadMotionFeatures} strict>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </LazyMotion>
  );
}

export function RouteContent({ children }: Readonly<{ children: ReactNode }>) {
  return <div>{children}</div>;
}
