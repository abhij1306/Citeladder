/**
 * Landing-page copy for the public "Proof" surface (see docs/design.md,
 * "Marketing creative system").
 *
 * Four writing rules govern this file:
 *   1. State what was measured, where, and when.
 *   2. Prefer "shows" and "observed" over "guarantees".
 *   3. Lead with the decision; keep the proof one step away.
 *   4. Never fabricate customer results, scale, or certainty.
 *
 * Rule 4 is why there are no invented numbers in page copy. The demo moment is
 * illustrative — it shows the SHAPE of what buyers ask and how engines answer —
 * and it says so on its face, rather than dressing a mock up as a real result.
 */

export type EngineAnswer = {
  engine: 'openai' | 'gemini' | 'claude';
  /** What the engine did with the brand: named it, cited it, or left it out. */
  outcome: 'named' | 'cited' | 'missing';
  /** The one-line observed answer, quoted. */
  answer: string;
};

export type DemoQuestion = {
  /** The buyer question, as a buyer would type it. */
  question: string;
  /** The category it probes, shown as the working context. */
  category: string;
  answers: readonly EngineAnswer[];
  /** The takeaway once the three answers are in. */
  verdict: string;
};

export const LANDING_CONTENT = {
  hook: {
    eyebrow: 'Verifiable market intelligence',
    title: 'Your buyers stopped Googling you.',
    /* The accent clause carries the signature slate→sage sweep, so the hero
       headline turns over to colour on its closing line. */
    titleAccent: 'They ask AI instead.',
    body: 'AI engines shape what your market buys. CiteLadder shows what they say about your brand — and links every claim to the answer behind it.',
    primaryCta: 'Book a demo',
    secondaryCta: 'See how it works',
  },

  shift: {
    kicker: 'The shift',
    title: 'The first page of search is now a conversation.',
    facts: [
      {
        label: 'Ask',
        title: 'Buyers ask before they browse.',
        body: 'Comparisons and shortlists start inside an answer engine — and often end there.',
      },
      {
        label: 'Cite',
        title: 'Answers cite, they don’t rank.',
        body: 'Either the engine names you and cites a page, or the category conversation happens without you.',
      },
      {
        label: 'Gap',
        title: 'You can’t fix what you can’t see.',
        body: 'Every engine answers differently. The same questions, run the same way, are the only measurement.',
      },
    ],
  },

  seeIt: {
    kicker: 'The solution',
    title: 'How teams turn AI search conversations into strategy.',
    cta: 'Run this on your market',
    questions: [
      {
        question: 'What are the best analytics tools for enterprise teams?',
        category: 'Enterprise analytics',
        answers: [
          {
            engine: 'openai',
            outcome: 'missing',
            answer: 'names three competitors — you’re not one of them',
          },
          {
            /* `missing`, not `cited`: the citation here goes to a RIVAL's page,
               so the brand is absent from the answer. Marking it `cited` made
               the chips contradict the verdict below ("two of three answer
               without you") — `cited` means the engine cited YOU. */
            engine: 'gemini',
            outcome: 'missing',
            answer: 'cites a rival’s comparison page as its source',
          },
          {
            engine: 'claude',
            outcome: 'missing',
            answer: 'recommends the category leader by name',
          },
        ],
        verdict:
          'All three engines answer without you. That’s the visibility gap — and it’s measurable.',
      },
      {
        question: 'Which help desk platform has the best customer support?',
        category: 'Customer support',
        answers: [
          {
            engine: 'openai',
            outcome: 'named',
            answer: 'names you — but credits a feature you deprecated',
          },
          {
            engine: 'gemini',
            outcome: 'cited',
            answer: 'cites your docs, alongside two competitors',
          },
          {
            engine: 'claude',
            outcome: 'named',
            answer: 'recommends you for mid-market, not enterprise',
          },
        ],
        verdict: 'You show up — but the story is stale. Now you know what to correct, and where.',
      },
      {
        question: 'What do reviewers say about self-serve BI tools?',
        category: 'Self-serve BI',
        answers: [
          {
            engine: 'openai',
            outcome: 'cited',
            answer: 'quotes a G2 thread that ranks you second',
          },
          {
            engine: 'gemini',
            outcome: 'missing',
            answer: 'summarises the category without naming you',
          },
          {
            engine: 'claude',
            outcome: 'cited',
            answer: 'cites your site for one criterion, a rival for the rest',
          },
        ],
        verdict: 'You’re in the conversation, not leading it. The gap is specific — and closable.',
      },
    ] satisfies readonly DemoQuestion[],
  },

  proof: {
    kicker: 'The operating loop',
    title: 'State. Evidence. Action. Improve.',
    intro: 'Every score opens to the answer, engine, artifact and rule that produced it.',
    /** The closing pull-quote: the verification standard, stated as a rule. */
    standard:
      'Persist the raw answer. Version the rules. Never let one model silently judge another.',
    steps: [
      {
        label: 'State',
        title: 'Where you stand',
        body: 'Visibility, share of voice, rank and movement — the current picture.',
      },
      {
        label: 'Evidence',
        title: 'What produced it',
        body: 'Mentions and citations from persisted answers, scored by versioned rules.',
      },
      {
        label: 'Action',
        title: 'What to do next',
        body: 'Gaps become a ranked queue, still linked to the answers behind them.',
      },
      {
        label: 'Improve',
        title: 'Measure again',
        body: 'Re-run on equal terms. Movement sits beside resolved work — without inventing causality.',
      },
    ],
  },

  cta: {
    kicker: 'Get started',
    title: 'Bring evidence to the conversation about your market.',
    body: 'A working session on your category, competitors and the questions buyers already ask.',
    primaryCta: 'Book a demo',
    secondaryCta: 'See pricing',
  },
} as const;

/**
 * The measurement axes every figure on the site carries.
 *
 * These are stated once, plainly, because a score without its conditions is
 * not evidence. Two rules govern the copy: it never implies a comparative cost
 * outcome, and it never implies scheduled execution — no dispatcher ships in
 * this release, so cadence is described strictly as an allowance.
 */
export const WHAT_WE_MEASURE = [
  {
    term: 'Measurement mode',
    detail:
      'Pulse for frequent checks; benchmark for the full prompt set. Never averaged together.',
  },
  {
    term: 'Exact model',
    detail:
      'One execution, one model. Aggregates list every model — never picks one to stand in for the rest.',
  },
  {
    term: 'Retrieval state',
    detail:
      'Web search on or off is frozen with the run. Same prompt, two states, two measurements.',
  },
  {
    term: 'Benchmark cadence',
    detail: 'An allowance you spend when you choose — nothing runs on its own.',
  },
] as const;

export const WHAT_WE_MEASURE_NOTE =
  'Trends stay partitioned by mode, model and retrieval — points under different conditions are never folded into one line.';
