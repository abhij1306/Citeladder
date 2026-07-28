import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { Meta } from '../primitives/label';
import { Section, SectionHeader } from '../primitives/section';
import { StaggerGroup, StaggerItem } from '../primitives/reveal';
import { WallpaperPanel } from '../scenes/wallpaper-panel';

/**
 * Why this category exists: what changed in how buyers search, and what that
 * breaks about the measurement teams already have. It has to land before the
 * method section — a visitor who does not accept the problem will not read
 * how the product solves it.
 *
 * Followed by the reporting commitments, which is the one place the page
 * talks about how Searchify writes about certainty. That is a promise a buyer
 * can hold us to, not a note about the design system.
 */
export function Shift() {
  const { shift, voice } = LANDING_CONTENT;
  return (
    <Section id="why" tone="sunken" rhythm="loose" aria-labelledby="shift-title">
      <SectionHeader
        index={shift.index}
        kicker={shift.kicker}
        title={shift.title}
        intro={shift.intro}
        headingId="shift-title"
      />

      <StaggerGroup className="border-mkt-line-soft grid border-y md:grid-cols-3">
        {shift.items.map((item) => (
          <StaggerItem
            key={item.num}
            className="border-mkt-line-soft flex min-h-[15rem] flex-col border-b p-8 last:border-b-0 md:border-r md:border-b-0 md:last:border-r-0"
          >
            <Meta className="text-mkt-ink-soft">{item.num}</Meta>
            {/* A FIXED gap under the number, not `mt-auto`. Pushing the block
                to the bottom aligned the three cards on their last line of
                body copy, which left the titles at three different heights. */}
            <div className="mt-16">
              <h3 className="font-mkt-display text-mkt-d4 text-mkt-ink mb-3.5 font-semibold">
                {item.title}
              </h3>
              <p className="text-mkt-sm text-mkt-ink-soft max-w-[40ch]">{item.body}</p>
            </div>
          </StaggerItem>
        ))}
      </StaggerGroup>

      <div className="rounded-mkt-lg mt-14 grid overflow-hidden shadow-card lg:grid-cols-[1.15fr_0.85fr]">
        <div className="bg-mkt-surface flex min-h-[15rem] flex-col justify-center p-9 md:p-11">
          <Meta as="p" className="mb-6">
            {voice.kicker}
          </Meta>
          <p className="font-mkt-display text-mkt-d2 text-mkt-ink max-w-[16ch] font-medium">
            {voice.quote} <em className="text-mkt-proof not-italic">{voice.quoteAccent}</em>{' '}
            {voice.quoteTail}
          </p>
        </div>

        <WallpaperPanel className="rounded-none border-0 border-t lg:border-t-0 lg:border-l">
          <div className="relative z-1 p-9 md:p-11">
            <Meta as="p" className="text-mkt-ink-muted mb-6">
              {voice.rulesLabel}
            </Meta>
            <ul className="grid gap-4">
              {voice.rules.map((rule) => (
                <li
                  key={rule.num}
                  className="border-mkt-line-soft text-mkt-ink-soft text-mkt-sm flex gap-3.5 border-b pb-4 last:border-b-0 last:pb-0"
                >
                  <b className="text-mkt-meta text-mkt-proof shrink-0 pt-0.5 font-mono tabular-nums">
                    {rule.num}
                  </b>
                  <span>{rule.text}</span>
                </li>
              ))}
            </ul>
          </div>
        </WallpaperPanel>
      </div>
    </Section>
  );
}
