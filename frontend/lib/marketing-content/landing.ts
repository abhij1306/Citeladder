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
 * Rule 4 is why there are no numbers here. The figures in the product scenes
 * (visibility 72.4, 1,248 answers, the provider ranking) are illustrative, so
 * they live inside the aria-hidden scene components with a visible "Example
 * data" mark — never in page copy, where they would read as a real result.
 *
 * NOTE: this is visitor-facing copy, not the design system's own vocabulary.
 * Words like "choreography", "restraint" and "motion 5/10" describe how the
 * site is BUILT; they belong in docs/design.md, never on the page.
 */

export type ShiftPoint = { num: string; title: string; body: string };
export type Step = { num: string; kicker: string; title: string; body: string };

export const LANDING_CONTENT = {
  hero: {
    eyebrow: 'Verifiable market intelligence',
    title: 'See your market through',
    accent: 'AI’s eyes.',
    body: 'Understand how the world’s answer engines describe your brand, products and competitors — then turn observed evidence into a sharper strategy.',
    secondaryCta: 'Explore the platform',
  },

  engines: {
    kicker: 'Coverage',
    title: 'The engines your buyers actually ask.',
    body: 'ChatGPT, Gemini and Claude are audited out of the box on your own provider keys. Paid workspaces can connect any other provider they hold keys for — the answer engines your buyers use, not the ones we happen to support.',
    /**
     * Buyer questions for the hero strip, rendered quoted and italic so they
     * read as things people ask rather than as claims we are making.
     *
     * Rule 4 still governs: these name generic software categories, never a
     * real company, and carry no numbers or outcomes. They illustrate the
     * SHAPE of what buyers ask an answer engine — comparisons, alternatives,
     * best-of lists — not anything Searchify has measured.
     */
    promptSamples: [
      'best analytics tools for enterprise teams',
      'top rated CRM software this year',
      'alternatives to the market leader in project management',
      'which help desk platform has the best support',
      'cheapest email marketing tool for small teams',
      'most reliable cloud hosting provider',
      'what do reviewers say about open source BI tools',
      'is an SEO platform worth it for a small business',
      'compare the leading data warehouse options',
      'which password manager do security teams recommend',
    ],
  },

  shift: {
    index: '01',
    kicker: 'The shift',
    title: 'The first page of search is now a conversation.',
    intro:
      'Buyers no longer compare ten blue links. They ask once, and act on the answer they get back. Your rank tracker did not come with them.',
    items: [
      {
        num: '01',
        title: 'Buyers ask before they browse',
        body: 'Comparisons, shortlists and “best tool for…” questions increasingly start inside an answer engine — and end there too.',
      },
      {
        num: '02',
        title: 'Answers cite, they do not rank',
        body: 'There is no position ten to climb from. Either the engine names you and cites a page, or your category conversation happens without you.',
      },
      {
        num: '03',
        title: 'You cannot fix what you cannot see',
        body: 'Every engine answers differently, and re-asking by hand is not a measurement. Knowing where you stand means running the same questions the same way, on a schedule.',
      },
    ] satisfies readonly ShiftPoint[],
  },

  voice: {
    kicker: 'How we report',
    quote: 'We do not predict the market. We',
    quoteAccent: 'observe',
    quoteTail: 'it carefully.',
    rulesLabel: 'What that commits us to',
    rules: [
      { num: '01', text: 'State what was measured, where, and when.' },
      { num: '02', text: 'Prefer “shows” and “observed” over “guarantees”.' },
      { num: '03', text: 'Lead with the decision; keep the proof one step away.' },
      { num: '04', text: 'Never fabricate customer results, scale, or certainty.' },
    ],
  },

  howItWorks: {
    index: '02',
    kicker: 'Method',
    title: 'Observe. Verify. Decide.',
    intro:
      'One run asks your buyers’ questions across every engine you cover, persists the raw answers, and scores them with versioned rules — so the same evidence always produces the same number.',
    steps: [
      {
        num: '01',
        kicker: 'Observe',
        title: 'Ask what your buyers ask',
        body: 'A prompt library that mirrors real buying questions — comparisons, best-of lists, alternatives — grouped by intent, market and product.',
      },
      {
        num: '02',
        kicker: 'Verify',
        title: 'Trace every answer to its source',
        body: 'Each response is persisted as an artifact. Mentions, citations and share of voice are computed from that text by versioned analyzers, never by one model judging another.',
      },
      {
        num: '03',
        kicker: 'Decide',
        title: 'Turn the pattern into strategy',
        body: 'Visibility gaps, competitor patterns and site evidence resolve into a prioritised set of moves — each one still linked to the answers behind it.',
      },
    ] satisfies readonly Step[],
  },

  platform: {
    index: '03',
    kicker: 'Product',
    title: 'One workspace for the whole market picture.',
    intro:
      'Visibility, competitors, products and site evidence share a single observation field, so a number you question is always one click from the answer that produced it.',
  },

  evidence: {
    index: '04',
    kicker: 'Evidence',
    title: 'Every metric opens to the answer it came from.',
    intro:
      'Scores are derived, not asserted. Open one and you get the observed answer, the provider that produced it, the persisted artifact and the rule version that scored it.',
  },

  stance: {
    index: '05',
    kicker: 'Stance',
    title: 'What we will and will not do.',
    intro:
      'Reporting on AI visibility is easy to fake. These are the commitments that make the difference legible from outside.',
    always: {
      title: 'Always',
      items: [
        'Attach every derived claim to inspectable evidence.',
        'Persist the raw answer behind each score.',
        'Version the rules, so a number can be reproduced.',
        'Run on your own provider keys, encrypted at rest.',
        'Keep workspace data isolated end to end.',
      ],
    },
    never: {
      title: 'Never',
      items: [
        'Score with one model silently judging another.',
        'Report a metric that cannot be traced to a source.',
        'Present estimates as observations.',
        'Return your provider keys, to you or to anyone else.',
        'Claim coverage of engines we do not audit.',
      ],
    },
  },

  compositions: {
    query: {
      tag: 'Query intelligence',
      title: 'See the questions shaping your category.',
      body: 'Group real buyer prompts by intent, market, product and provider — then trace the answers they produce.',
      cards: [
        'Which platform is trusted by enterprise teams?',
        'Best AI visibility tools for global agencies',
        'How does Searchify verify its metrics?',
      ],
    },
    strategy: {
      tag: 'Strategic intelligence',
      title: 'Move from observation to your next best action.',
      body: 'Searchify connects visibility gaps, competitor patterns, site evidence and product presence into a prioritised strategy.',
    },
    quote: {
      text: 'The result should feel less like a dashboard making claims — and more like a research team showing its work.',
      attribution: 'How we build it',
      detail: 'Evidence before persuasion',
      mark: 'Searchify',
    },
  },

  finalCta: {
    kicker: 'Get started',
    title: 'Bring evidence to the conversation about your market.',
    body: 'A working session on your category, your competitors and the questions your buyers are already asking answer engines.',
  },
} as const;
