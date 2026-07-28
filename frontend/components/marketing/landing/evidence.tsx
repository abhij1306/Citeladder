import { ArrowUpRight, FileCheck2 } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { Badge, VerifiedMark } from '../primitives/badge';
import { EngineDot, type EngineKey } from '../primitives/engine-chip';
import { Meta } from '../primitives/label';
import { Reveal } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';
import { ExampleDataNote, Panel, WallpaperPanel } from '../scenes/wallpaper-panel';

/**
 * The evidence chapter: what a traced result actually looks like. A table of
 * observed answers beside the score they roll up into — the two halves of the
 * product's central claim, shown together so the link between them is the
 * point rather than a footnote.
 *
 * Illustrative rows, so the product scene is aria-hidden and marked as
 * example data. The section's real argument lives in the heading and the
 * explanatory note under the score, which remain readable by everyone.
 */
const ROWS: readonly {
  answer: string;
  engine: EngineKey;
  finding: string;
  tone: 'good' | 'proof' | 'warn';
}[] = [
  {
    answer: 'Best analytics platforms for enterprise teams',
    engine: 'openai',
    finding: 'Mentioned',
    tone: 'good',
  },
  {
    answer: 'How to measure brand visibility in AI answers',
    engine: 'claude',
    finding: 'Cited',
    tone: 'proof',
  },
  {
    answer: 'Searchify alternatives for global agencies',
    engine: 'gemini',
    finding: 'Review',
    tone: 'warn',
  },
];

/**
 * Desktop renders an actual table; mobile renders a stacked card list — the
 * two share nothing but the row data, so each gets a layout that fits its
 * width instead of one squeezed grid pretending to be both.
 */
const DESKTOP_GRID =
  'hidden lg:grid lg:grid-cols-[minmax(0,1fr)_8.5rem_8rem] lg:items-center lg:gap-x-4';

export function Evidence() {
  const { evidence } = LANDING_CONTENT;
  return (
    <Section id="evidence" tone="surface" rhythm="loose" aria-labelledby="evidence-title">
      <SectionHeader
        index={evidence.index}
        kicker={evidence.kicker}
        title={evidence.title}
        intro={evidence.intro}
        headingId="evidence-title"
      />

      <Reveal>
        <WallpaperPanel className="p-2 sm:p-5 lg:p-7">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3 px-1 sm:px-2">
            <div className="flex items-center gap-3">
              <span className="border-mkt-line bg-mkt-surface text-mkt-proof grid size-8 place-items-center rounded-full border">
                <FileCheck2 aria-hidden className="size-4" strokeWidth={1.8} />
              </span>
              <Meta as="p" className="text-mkt-ink-muted">
                Audit evidence / selected run
              </Meta>
            </div>
            <ExampleDataNote />
          </div>

          <div
            aria-hidden
            className="grid gap-2.5 sm:gap-3 xl:grid-cols-[minmax(0,1.45fr)_minmax(20rem,0.75fr)]"
          >
            <Panel className="overflow-hidden">
              {/* Mobile: one honest card header. Desktop: the table header. */}
              <div className="border-mkt-line-soft bg-mkt-paper-raised flex items-center justify-between gap-3 border-b px-4 py-2.5 lg:hidden">
                <Meta as="p" className="text-mkt-ink-muted">
                  Observed answers
                </Meta>
                <Meta as="p" className="text-mkt-ink-muted">
                  3 persisted
                </Meta>
              </div>
              <div
                className={`${DESKTOP_GRID} border-mkt-line-soft bg-mkt-paper-raised border-b px-5 py-3 sm:px-6`}
              >
                <div className="grid grid-cols-[1.75rem_minmax(0,1fr)] items-center gap-3">
                  <span aria-hidden className="size-7" />
                  <div>
                    <Meta as="p" className="text-mkt-ink-muted">
                      Observed answer
                    </Meta>
                    <p className="text-mkt-sm text-mkt-ink-soft mt-1">3 persisted responses</p>
                  </div>
                </div>
                <Meta className="text-mkt-ink-muted">Provider</Meta>
                <Meta className="text-mkt-ink-muted justify-self-start">Finding</Meta>
              </div>

              {ROWS.map(({ answer, engine, finding, tone }, index) => (
                <div
                  key={answer}
                  className="border-mkt-line-soft group border-b px-4 py-3 last:border-b-0 sm:px-6 lg:px-5"
                >
                  {/* Mobile: answer full width, one meta line, badge pinned right. */}
                  <div className="lg:hidden">
                    <strong className="text-mkt-ink text-mkt-body block leading-snug font-semibold">
                      {answer}
                    </strong>
                    <div className="mt-2 flex items-center gap-3">
                      <EngineDot engine={engine} />
                      <Badge tone={tone} className="ml-auto shrink-0">
                        {finding}
                      </Badge>
                    </div>
                  </div>
                  {/* Desktop: the table row. */}
                  <div className={DESKTOP_GRID}>
                    <div className="grid grid-cols-[1.75rem_minmax(0,1fr)] items-start gap-3">
                      <span className="bg-mkt-paper-raised text-mkt-ink-muted text-mkt-meta mt-0.5 grid size-7 place-items-center rounded-full font-mono tabular-nums">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      <strong className="text-mkt-ink text-mkt-body block max-w-[34ch] leading-snug font-semibold">
                        {answer}
                      </strong>
                    </div>
                    <EngineDot engine={engine} />
                    <Badge tone={tone} className="justify-self-start">
                      {finding}
                    </Badge>
                  </div>
                </div>
              ))}
            </Panel>

            <Panel className="flex flex-col p-4 sm:p-5">
              <div className="flex items-center justify-between gap-3">
                <p className="text-mkt-ink text-mkt-sm font-semibold">Visibility index</p>
                <span className="border-mkt-line bg-mkt-paper-raised text-mkt-ink-muted text-mkt-meta inline-flex items-center gap-1.5 rounded-full border px-2 py-1 uppercase">
                  Formula v4.2
                  <ArrowUpRight className="size-3" strokeWidth={1.8} />
                </span>
              </div>
              <div className="mt-1.5">
                <VerifiedMark>Reproducible</VerifiedMark>
              </div>

              <div className="my-5 flex items-end gap-3">
                <strong className="text-mkt-ink font-mono text-5xl leading-none font-medium tabular-nums sm:text-6xl">
                  72.4
                </strong>
                <span className="text-mkt-sm text-mkt-ink-soft pb-1 font-mono tabular-nums">
                  / 100
                </span>
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <Meta className="text-mkt-proof">Strong visibility</Meta>
                  <Meta className="text-mkt-ink-muted">+4.8 this run</Meta>
                </div>
                <div className="bg-mkt-surface-sunk relative h-2 overflow-hidden rounded-full">
                  <span className="bg-mkt-proof block h-full w-[72.4%] rounded-full" />
                  <span className="bg-mkt-surface ring-mkt-proof absolute top-1/2 left-[72.4%] size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2" />
                </div>
              </div>

              <div className="border-mkt-line-soft mt-5 grid grid-cols-3 border-y py-3">
                {[
                  ['3 / 3', 'Artifacts'],
                  ['2', 'Signals'],
                  ['1', 'Review'],
                ].map(([value, label], index) => (
                  <div
                    key={label}
                    className={`px-3 first:pl-0 last:pr-0 ${index > 0 ? 'border-mkt-line-soft border-l' : ''}`}
                  >
                    <strong className="text-mkt-ink block font-mono text-base font-medium tabular-nums">
                      {value}
                    </strong>
                    <Meta className="mt-1 block">{label}</Meta>
                  </div>
                ))}
              </div>

              <p className="text-mkt-sm text-mkt-ink-soft mt-auto pt-5">
                Computed from persisted answers, with every point traceable to its source artifact.
              </p>
            </Panel>
          </div>
        </WallpaperPanel>
      </Reveal>
    </Section>
  );
}
