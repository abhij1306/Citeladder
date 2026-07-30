'use client';

import { useRef, useState } from 'react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { Reveal, StaggerGroup, StaggerItem } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';

function SpotlightCard({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [opacity, setOpacity] = useState(0);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!cardRef.current) return;
    const rect = cardRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    cardRef.current.style.setProperty('--mouse-x', `${x}px`);
    cardRef.current.style.setProperty('--mouse-y', `${y}px`);
    if (opacity !== 1) setOpacity(1);
  };

  const handleMouseLeave = () => {
    setOpacity(0);
  };

  return (
    <div
      ref={cardRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      className={`rounded-mkt-lg hover:bg-mkt-surface/80 relative p-5 transition-all duration-300 ${className}`}
    >
      {/* Radial cursor spotlight glow */}
      <div
        className="rounded-mkt-lg pointer-events-none absolute -inset-px opacity-0 transition-opacity duration-300"
        style={{
          opacity,
          background: `radial-gradient(400px circle at var(--mouse-x, 0px) var(--mouse-y, 0px), color-mix(in srgb, var(--color-mkt-proof) 12%, transparent), transparent 80%)`,
        }}
      />
      {children}
    </div>
  );
}

/**
 * The "so how is this real" beat — the three steps as cursor-spotlight cards.
 */
export function Proof() {
  const { proof } = LANDING_CONTENT;

  return (
    <Section id="how-it-works" tone="sunken" rhythm="loose" aria-labelledby="proof-title">
      <SectionHeader
        kicker={proof.kicker}
        title={proof.title}
        intro={proof.intro}
        headingId="proof-title"
      />
      <StaggerGroup className="grid gap-8 md:grid-cols-3">
        {proof.steps.map((step) => (
          <StaggerItem key={step.num} className="relative">
            <SpotlightCard className="h-full">
              <p className="text-mkt-meta text-mkt-ink-muted font-mono uppercase">
                {step.num} / {step.kicker}
              </p>
              <h3 className="font-mkt-display text-mkt-ink text-mkt-d5 mt-3">{step.title}</h3>
              <p className="text-mkt-sm text-mkt-ink-soft mt-3 max-w-[36ch]">{step.body}</p>
            </SpotlightCard>
          </StaggerItem>
        ))}
      </StaggerGroup>
      <Reveal className="mt-12">
        <p className="text-mkt-body text-mkt-ink border-mkt-proof max-w-[52ch] border-l-2 pl-5 font-semibold">
          {proof.standard}
        </p>
      </Reveal>
    </Section>
  );
}
