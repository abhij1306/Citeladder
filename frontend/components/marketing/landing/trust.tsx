import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { Eyebrow } from '../primitives/label';
import { Reveal } from '../primitives/reveal';
import { Section } from '../primitives/section';
import { LANDING_ICONS } from './landing-icons';

/**
 * Enterprise trust — an asymmetric split between the promise and one concise
 * proof ledger. Each guarantee appears once, with its supporting detail.
 */
export function Trust() {
  const { trust } = LANDING_CONTENT;
  return (
    <Section id="trust" tone="sunken" rhythm="base" aria-labelledby="trust-title">
      <div className="grid items-center gap-x-16 gap-y-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <Reveal className="lg:py-8">
          <Eyebrow>{trust.kicker}</Eyebrow>
          <h2
            id="trust-title"
            className="website-section-heading text-foreground mt-6 max-w-[20ch] text-balance"
          >
            {trust.title}
          </h2>
          <p className="website-body-lg text-muted mt-5 max-w-[52ch]">{trust.lead}</p>
        </Reveal>

        <Reveal className="bg-panel overflow-hidden rounded-[var(--radius-card)]">
          <dl className="divide-border divide-y">
            {trust.guarantees.map((guarantee) => {
              const Icon = LANDING_ICONS[guarantee.icon];
              return (
                <div
                  key={guarantee.title}
                  className="hover:bg-background-alt/50 grid grid-cols-[40px_1fr] gap-4 p-5 transition-colors sm:p-6"
                >
                  <span className="bg-accent-subtle/80 text-accent-text flex size-10 items-center justify-center rounded-sm">
                    <Icon className="size-4.5" strokeWidth={1.75} aria-hidden />
                  </span>
                  <div>
                    <dt className="website-body text-foreground font-medium">{guarantee.title}</dt>
                    <dd className="website-body text-muted mt-1">{guarantee.description}</dd>
                  </div>
                </div>
              );
            })}
          </dl>
        </Reveal>
      </div>
    </Section>
  );
}
