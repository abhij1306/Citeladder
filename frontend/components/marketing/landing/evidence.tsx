import { ArrowUpRight, FileCheck2 } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { Badge, VerifiedMark } from '../primitives/badge';
import { EngineDot, type EngineKey } from '../primitives/engine-chip';
import { Meta } from '../primitives/label';
import { Reveal } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';
import { ExampleDataNote, GlassPanel, WallpaperPanel } from '../scenes/wallpaper-panel';

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

const TABLE_GRID =
  'grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-5 lg:grid-cols-[minmax(0,1fr)_8.5rem_8rem] lg:gap-x-4';

export function Evidence() {
  const { evidence } = LANDING_CONTENT;
  return (
    <Section id="evidence" rhythm="loose" divided aria-labelledby="evidence-title">
      <SectionHeader
        index={evidence.index}
        kicker={evidence.kicker}
        title={evidence.title}
        intro={evidence.intro}
        headingId="evidence-title"
      />

      <Reveal>
        <WallpaperPanel className="p-3 sm:p-5 lg:p-7">
          <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3 px-1 sm:px-2">
            <div className="flex items-center gap-3">
              <span className="border-mkt-glass-line bg-mkt-glass text-mkt-proof-text grid size-8 place-items-center rounded-full border backdrop-blur-md">
                <FileCheck2 aria-hidden className="size-4" strokeWidth={1.8} />
              </span>
              <Meta as="p" className="text-mkt-slate-soft">
                Audit evidence / selected run
              </Meta>
            </div>
            <ExampleDataNote />
          </div>

          <div
            aria-hidden
            className="grid gap-3.5 xl:grid-cols-[minmax(0,1.45fr)_minmax(20rem,0.75fr)]"
          >
            <GlassPanel className="overflow-hidden">
              <div
                className={`${TABLE_GRID} border-mkt-glass-line bg-mkt-glass-soft border-b px-5 py-4 sm:px-6`}
              >
                <div className="grid grid-cols-[1.75rem_minmax(0,1fr)] items-center gap-3">
                  <span aria-hidden className="size-7" />
                  <div>
                    <Meta as="p" className="text-mkt-slate-soft">
                      Observed answer
                    </Meta>
                    <p className="text-mkt-sm text-mkt-slate mt-1">3 persisted responses</p>
                  </div>
                </div>
                <Meta className="text-mkt-slate-soft hidden lg:block">Provider</Meta>
                <Meta className="text-mkt-slate-soft justify-self-start">Finding</Meta>
              </div>

              {ROWS.map(({ answer, engine, finding, tone }, index) => (
                <div
                  key={answer}
                  className={`${TABLE_GRID} border-mkt-glass-line group min-h-[6.25rem] border-b px-5 py-4 last:border-b-0 sm:px-6`}
                >
                  <div className="grid grid-cols-[1.75rem_minmax(0,1fr)] items-start gap-3">
                    <span className="bg-mkt-paper-raised text-mkt-ink-muted mkt-num text-mkt-meta mt-0.5 grid size-7 place-items-center rounded-full">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <div>
                      <strong className="text-mkt-ink text-mkt-body block max-w-[34ch] leading-snug font-semibold">
                        {answer}
                      </strong>
                      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 lg:hidden">
                        <EngineDot engine={engine} />
                      </div>
                    </div>
                  </div>
                  <EngineDot engine={engine} className="hidden lg:inline-flex" />
                  <Badge tone={tone} className="justify-self-end lg:justify-self-start">
                    {finding}
                  </Badge>
                </div>
              ))}
            </GlassPanel>

            <GlassPanel className="flex min-h-[25rem] flex-col p-5 sm:p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <Meta as="p" className="text-mkt-slate-soft">
                    Visibility index
                  </Meta>
                  <VerifiedMark>Reproducible</VerifiedMark>
                </div>
                <span className="border-mkt-line bg-mkt-paper-raised text-mkt-ink-muted text-mkt-meta rounded-mkt-pill inline-flex items-center gap-1.5 border px-2.5 py-1.5 uppercase">
                  Formula v4.2
                  <ArrowUpRight className="size-3" strokeWidth={1.8} />
                </span>
              </div>

              <div className="my-8 flex items-end gap-3 sm:my-10">
                <strong className="font-mkt-display text-mkt-ink mkt-num text-[5.25rem] leading-[0.8] font-medium tracking-[-0.075em]">
                  72.4
                </strong>
                <span className="text-mkt-sm text-mkt-slate mkt-num pb-1.5">/ 100</span>
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <Meta className="text-mkt-proof-text">Strong visibility</Meta>
                  <Meta className="text-mkt-slate-soft">+4.8 this run</Meta>
                </div>
                <div className="bg-mkt-surface-sunk relative h-2 overflow-hidden rounded-full">
                  <span className="bg-mkt-proof block h-full w-[72.4%] rounded-full" />
                  <span className="bg-mkt-surface ring-mkt-proof absolute top-1/2 left-[72.4%] size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2" />
                </div>
              </div>

              <div className="border-mkt-line mt-6 grid grid-cols-3 border-y py-4">
                {[
                  ['3 / 3', 'Artifacts'],
                  ['2', 'Signals'],
                  ['1', 'Review'],
                ].map(([value, label], index) => (
                  <div
                    key={label}
                    className={`px-3 first:pl-0 last:pr-0 ${index > 0 ? 'border-mkt-line border-l' : ''}`}
                  >
                    <strong className="text-mkt-ink mkt-num block text-lg font-medium">
                      {value}
                    </strong>
                    <Meta className="mt-1 block">{label}</Meta>
                  </div>
                ))}
              </div>

              <p className="text-mkt-sm text-mkt-ink-soft mt-auto pt-6">
                Computed from persisted answers, with every point traceable to its source artifact.
              </p>
            </GlassPanel>
          </div>
        </WallpaperPanel>
      </Reveal>
    </Section>
  );
}
