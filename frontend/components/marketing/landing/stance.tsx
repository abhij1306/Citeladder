import { Check, X } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { Section, SectionHeader } from '../primitives/section';
import { StaggerGroup, StaggerItem } from '../primitives/reveal';

/**
 * The commitments band. Reporting on AI visibility is trivially fakeable, so
 * the differentiator is not a feature list — it is what the product refuses
 * to do. Stating both halves side by side is the only version of this that
 * carries information; an "Always" column on its own is just marketing.
 */
export function Stance() {
  const { stance } = LANDING_CONTENT;
  const columns = [
    { ...stance.always, Icon: Check, tone: 'text-mkt-evidence-text' },
    { ...stance.never, Icon: X, tone: 'text-mkt-signal-text' },
  ];

  return (
    <Section tone="paper" rhythm="loose" aria-labelledby="stance-title">
      <SectionHeader
        index={stance.index}
        kicker={stance.kicker}
        title={stance.title}
        intro={stance.intro}
        headingId="stance-title"
      />
      <StaggerGroup className="grid gap-4 md:grid-cols-2">
        {columns.map(({ title, items, Icon, tone }) => (
          <StaggerItem key={title} className="rounded-mkt-lg bg-mkt-surface shadow-card p-8 md:p-9">
            <h3 className="font-mkt-display text-mkt-ink text-heading-sm mb-6 font-semibold">
              {title}
            </h3>
            <ul className="grid gap-3.5">
              {items.map((item) => (
                <li key={item} className="text-mkt-sm text-mkt-ink-soft flex gap-3">
                  <Icon aria-hidden className={`mt-0.5 size-4 shrink-0 ${tone}`} />
                  {item}
                </li>
              ))}
            </ul>
          </StaggerItem>
        ))}
      </StaggerGroup>
    </Section>
  );
}
