/**
 * Landing-page copy for the public "Proof" surface, following the approved
 * brand deck (docs/searchify-brand-deck.html).
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
    body: 'AI engines shape what your market buys. Searchify shows what they say about your brand — and links every claim to the answer behind it.',
    primaryCta: 'See it on your category',
    secondaryCta: 'How it works',
  },

  shift: {
    kicker: 'The shift',
    title: 'The first page of search is now a conversation.',
    facts: [
      {
        num: '01',
        title: 'Buyers ask before they browse.',
        body: 'Comparisons, shortlists and “best tool for…” questions start inside an answer engine — and increasingly end there too.',
      },
      {
        num: '02',
        title: 'Answers cite, they don’t rank.',
        body: 'There is no position ten to climb from. Either the engine names you and cites a page, or your category conversation happens without you.',
      },
      {
        num: '03',
        title: 'You can’t fix what you can’t see.',
        body: 'Every engine answers differently, and re-asking by hand is not a measurement. You have to run the same questions the same way, on a schedule.',
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
    kicker: 'Proof',
    title: 'Every number opens to the answer it came from.',
    intro:
      'Scores are derived, not asserted. Open one and you get the answer, the engine, the persisted artifact and the rule version behind it — so the same evidence always yields the same number.',
    /** The closing pull-quote: the verification standard, stated as a rule. */
    standard:
      'Persist the raw answer behind every score. Version the rules that produced it. Never let one model silently judge another.',
    steps: [
      {
        num: '01',
        kicker: 'Observe',
        title: 'Ask what your buyers ask',
        body: 'One run asks your real buyer questions across every engine, on your own provider keys.',
      },
      {
        num: '02',
        kicker: 'Verify',
        title: 'Trace every answer to its source',
        body: 'Each response is persisted. Mentions, citations and share of voice are computed from that text by versioned rules — never one model judging another.',
      },
      {
        num: '03',
        kicker: 'Decide',
        title: 'Turn the pattern into strategy',
        body: 'Visibility gaps and competitor patterns resolve into prioritised moves, each still linked to the answers behind it.',
      },
    ],
  },

  cta: {
    kicker: 'Get started',
    title: 'Bring evidence to the conversation about your market.',
    body: 'A working session on your category, your competitors and the questions your buyers are already asking answer engines.',
    primaryCta: 'Book a working session',
    secondaryCta: 'See pricing',
  },
} as const;
