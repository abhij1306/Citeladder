'use client';

import { LazyMotion } from 'motion/react';
import dynamic from 'next/dynamic';
import type { ReactNode } from 'react';

/**
 * The marketing tree's one animation boundary. It exists for two reasons that
 * both need a client component, so they share one.
 *
 * **1. `m` components had no features.** `m` is the lightweight motion element:
 * it is created WITHOUT the feature bundle and without a visual-element factory
 * (`createMotionComponent(C, opts)` versus `motion`'s
 * `createMotionComponent(C, opts, featureBundle, createDomVisualElement)`), and
 * gets both from a `LazyMotion` ancestor. There was no such ancestor, so every
 * `m` in the marketing tree rendered as an inert element — the nav's `layout`
 * lens and `product-window`'s `AnimatePresence` exits silently did nothing
 * while still paying for `motion-dom` in the bundle. `domMax` rather than
 * `domAnimation` because the nav animates `layout`, which only `domMax` carries.
 *
 * The feature bundle is loaded through a FUNCTION, not imported eagerly: that is
 * what keeps it in its own async chunk instead of the initial payload.
 *
 * **2. GSAP does not belong in the server build.** `GsapRevealInitializer`
 * returns `null` — it animates elements that are already present in the
 * server-rendered HTML. Deferring it with `ssr: false` therefore removes GSAP
 * and ScrollTrigger (~53 KB) from the server bundle at zero cost: no markup is
 * withheld from crawlers, and nothing shifts, because the component never
 * rendered anything to begin with. Content is fully visible before the
 * animation code arrives; the reveal simply starts a beat later.
 *
 * `ssr: false` cannot be declared in the Server Component layout itself, which
 * is the other reason this boundary exists.
 */

const GsapRevealInitializer = dynamic(
  () => import('./gsap-reveal-initializer').then((mod) => mod.GsapRevealInitializer),
  { ssr: false },
);

const loadMotionFeatures = () => import('motion/react').then((mod) => mod.domMax);

export function MarketingMotion({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <LazyMotion features={loadMotionFeatures}>
      <GsapRevealInitializer />
      {children}
    </LazyMotion>
  );
}
