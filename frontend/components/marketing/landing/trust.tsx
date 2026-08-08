import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { Eyebrow } from '../primitives/label';
import { Reveal } from '../primitives/reveal';
import { Section } from '../primitives/section';
import { LANDING_ICONS } from './landing-icons';

/**
 * Enterprise trust — an asymmetric split: the promise and four proof tiles on
 * the left, a plain-language evidence ledger on the right. No seals or badges;
 * the claim is the design.
 */
export function Trust() {
  const { trust } = LANDING_CONTENT;
  return (
    <Section id="trust" tone="paper" rhythm="base" aria-labelledby="trust-title">
      <div className="grid items-start gap-x-12 gap-y-10 lg:grid-cols-2">
        <Reveal>
          <Eyebrow>{trust.kicker}</Eyebrow>
          <h2
            id="trust-title"
            className="font-display text-foreground mt-6 max-w-[20ch] text-2xl font-semibold tracking-tight text-balance"
          >
            {trust.title}
          </h2>
          <p className="text-muted mt-5 max-w-[52ch] text-base leading-relaxed">{trust.lead}</p>
          <div className="mt-8 grid gap-4 sm:grid-cols-2">
            {trust.features.map((feature) => {
              const Icon = LANDING_ICONS[feature.icon];
              return (
                <div
                  key={feature.title}
                  className="bg-panel border-border shadow-card hover:shadow-card-hover flex gap-3.5 rounded-xl border p-4.5 transition-shadow duration-300"
                >
                  <span className="bg-accent-subtle/80 text-accent-text border-accent-border/60 flex size-9 shrink-0 items-center justify-center rounded-lg border shadow-xs">
                    <Icon className="size-4.5" strokeWidth={1.75} aria-hidden />
                  </span>
                  <div>
                    <p className="text-foreground text-sm font-semibold">{feature.title}</p>
                    <p className="text-muted mt-1 text-xs leading-relaxed">{feature.sub}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </Reveal>

        <Reveal className="bg-panel border-border shadow-card overflow-hidden rounded-xl border">
          <dl className="divide-border divide-y">
            {trust.ledger.map((row) => (
              <div
                key={row.label}
                className="hover:bg-background-alt/50 grid gap-1 p-5 transition-colors sm:grid-cols-[200px_1fr] sm:gap-4"
              >
                <dt className="text-foreground text-sm font-semibold">{row.label}</dt>
                <dd className="text-muted text-sm leading-relaxed">{row.value}</dd>
              </div>
            ))}
          </dl>
        </Reveal>
      </div>
    </Section>
  );
}
