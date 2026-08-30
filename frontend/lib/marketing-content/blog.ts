/**
 * Blog content for /blog and /blog/[slug].
 *
 * Posts render straight from this module. Every claim must be grounded in this
 * repository — no invented numbers, customer results, or dates. Owner-supplied
 * byline fields (`date`, `readTime`, `author`) are optional: while absent the
 * byline is omitted rather than showing a placeholder.
 *
 * Copy rule: buyer-facing commitments only — no internal version ids, rule
 * counts, or formula names.
 */

export type BlogBlock =
  | { type: 'paragraph' | 'heading'; text: string }
  | { type: 'list'; items: readonly string[] };

export type BlogPost = {
  slug: string;
  title: string;
  excerpt: string;
  /** Owner-supplied. Byline row is omitted entirely while absent. */
  date?: string;
  /** Owner-supplied. */
  readTime?: string;
  /** Owner-supplied. */
  author?: string;
  tags: readonly string[];
  body: readonly BlogBlock[];
};

export const POSTS: readonly BlogPost[] = [
  {
    slug: 'how-we-measure-ai-visibility-deterministically',
    title: 'How we measure AI visibility deterministically',
    excerpt:
      'Most AI-visibility numbers come from one model grading another. Ours come from ' +
      'persisted answers and versioned rules — same evidence, same score, always checkable.',
    tags: ['Method', 'Evidence'],
    body: [
      {
        type: 'paragraph',
        text:
          'Most AI-visibility tools hand you a number and ask you to trust it. If you cannot ' +
          'recompute a score from the evidence behind it, the score is an opinion. Three ' +
          'commitments keep ours out of that category.',
      },
      { type: 'heading', text: 'No model grades another' },
      {
        type: 'paragraph',
        text:
          'Mentions, citations and share of voice are derived from persisted response text by ' +
          'explicit rules — not an LLM judge. The raw answer is stored first; every headline ' +
          'figure is computed from that artifact. Point at the text and you can explain the ' +
          'classification.',
      },
      { type: 'heading', text: 'Every number carries its rule version' },
      {
        type: 'paragraph',
        text:
          'Each projection is stamped with the analyzer and rule version that produced it. ' +
          'When a score moves between runs, you can tell whether the engines answered ' +
          'differently or the rules did — the two cases that matter.',
      },
      { type: 'heading', text: 'Site health you can inspect' },
      {
        type: 'paragraph',
        text:
          'Built-in Web Fundamentals, Web Fundamentals, and AEO checks use inspectable outcomes. ' +
          'Scores remain visible with their evidence coverage; unmeasured results are never fabricated.',
      },
      { type: 'heading', text: 'Three engines, your keys' },
      {
        type: 'paragraph',
        text:
          'We audit ChatGPT, Gemini and Claude — one approved route each. Runs use your ' +
          'workspace keys, encrypted at rest and never returned by the API. Usage bills to ' +
          'your provider accounts at their rates.',
      },
      {
        type: 'paragraph',
        text:
          'Open any score and you are one click from the persisted answer, the rule version ' +
          'that scored it, and the run that produced both. If we ever ask you to trust a ' +
          'number without the working, treat it with the suspicion it deserves.',
      },
    ],
  },
];

export type BlogEmptyState = {
  heading: string;
  body: string;
};

/** Shown on /blog when POSTS is empty. */
export const BLOG_EMPTY_STATE: BlogEmptyState = {
  heading: 'First posts are on the way.',
  body: 'Notes on AEO and evidence-first measurement — until then, try the product.',
};
