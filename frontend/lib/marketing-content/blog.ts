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
    title: 'How to measure AI visibility with evidence you can audit',
    excerpt:
      'A practical explanation of answer-engine measurement: persist the answer, apply explicit ' +
      'rules, show coverage, and keep every score tied to the evidence that produced it.',
    tags: ['AI visibility', 'Measurement'],
    body: [
      {
        type: 'paragraph',
        text:
          'AI visibility is not a single ranking position. It is an observation of what an answer ' +
          'engine says when a defined audience asks a defined question. A useful measurement ' +
          'therefore needs the prompt, the engine, the response, and the rules used to interpret it.',
      },
      { type: 'heading', text: 'Start with the answer, not a verdict' },
      {
        type: 'paragraph',
        text:
          'The raw response is the primary evidence. Mentions, citations, recommendation presence, ' +
          'and observed share are derived from that persisted artifact with explicit rules. A model ' +
          'does not grade another model to create the headline number.',
      },
      { type: 'heading', text: 'Make the measurement reproducible' },
      {
        type: 'paragraph',
        text:
          'A comparable run freezes the prompt portfolio, engine selection, and relevant analysis ' +
          'versions. When the result moves, the audit trail lets you separate a changed answer ' +
          'from a changed interpretation.',
      },
      {
        type: 'list',
        items: [
          'Persist the exact answer and its provider attempt before deriving metrics.',
          'Keep prompt, engine, repetition, and analysis context with each observation.',
          'Show coverage and limitations next to every aggregate, including unavailable and zero states.',
        ],
      },
      { type: 'heading', text: 'Treat coverage as part of the result' },
      {
        type: 'paragraph',
        text:
          'A percentage without its denominator invites false confidence. CiteLadder keeps observed ' +
          'zero, unavailable, not configured, and incomplete coverage distinct, so a team can tell ' +
          'what was measured and what still needs evidence.',
      },
      { type: 'heading', text: 'Use the result to decide what to improve' },
      {
        type: 'paragraph',
        text:
          'The measurement is a starting point for action, not proof of causality. Pair answer ' +
          'evidence with site health, demand signals, and the content changes your team chooses. ' +
          'Later audits report what was observed after the change without claiming that the change caused it.',
      },
      {
        type: 'paragraph',
        text:
          'That is the standard we use for AI visibility: a number is useful when a teammate can open ' +
          'it, inspect the answer behind it, understand its coverage, and explain how it was derived.',
      },
    ],
  },
  {
    slug: 'a-practical-aeo-audit-from-crawl-to-citation',
    title: 'A practical AEO audit: from crawl to citation evidence',
    excerpt:
      'A step-by-step framework for finding the pages, facts, and answer-engine observations that ' +
      'should shape your next content decision.',
    tags: ['AEO', 'Field guide'],
    body: [
      {
        type: 'paragraph',
        text:
          'Answer-engine optimization starts before a prompt is run. If important pages are hard to ' +
          'discover, structurally unclear, or unsupported by visible facts, a citation report cannot ' +
          'tell you what to fix first. An audit connects those observations into one workflow.',
      },
      { type: 'heading', text: '1. Establish the pages and facts you own' },
      {
        type: 'paragraph',
        text:
          'Begin with a bounded crawl of the owned site. Record the fetched artifact, normalize the ' +
          'page facts, and classify each supported page by its structural purpose. A page without ' +
          'enough evidence stays unclassified rather than being forced into a generic verdict.',
      },
      { type: 'heading', text: '2. Apply checks that fit the page' },
      {
        type: 'paragraph',
        text:
          'A product page, article, FAQ, and organization page do not have the same job. Page-kind ' +
          'checks should test the signals that matter for that job: visible headings and content, ' +
          'links, metadata, delivery, and structured data. Structured data can support classification, ' +
          'but it cannot certify the schema being checked.',
      },
      { type: 'heading', text: '3. Turn demand into a prompt portfolio' },
      {
        type: 'paragraph',
        text:
          'Use search and journey evidence to define the questions your audience actually asks. Keep ' +
          'the portfolio explicit: each prompt has an intent, an audience, and a reason it belongs in ' +
          'the measurement. This makes later runs comparable instead of turning them into a random sample.',
      },
      {
        type: 'list',
        items: [
          'Connect owned pages, demand sources, and approved provider routes.',
          'Analyze structural gaps and answer-engine responses against the same project context.',
          'Prioritize an opportunity with its evidence, scope, and suggested content handoff.',
          'After publication, recrawl or rerun the same cohort and report the observation.',
        ],
      },
      { type: 'heading', text: '4. Read citations as observations' },
      {
        type: 'paragraph',
        text:
          'A citation shows that a source appeared in a particular response under particular ' +
          'conditions. It does not prove that the source caused a ranking, traffic, or revenue result. ' +
          'Keep that distinction visible when sharing an AEO report with stakeholders.',
      },
    ],
  },
  {
    slug: 'why-ai-visibility-scores-need-provenance',
    title: 'Why AI visibility scores need provenance',
    excerpt:
      'The fastest way to lose trust in an AI report is to hide the answer, coverage, or rule behind ' +
      'the score. Here is the audit trail a useful metric needs.',
    tags: ['Evidence', 'Governance'],
    body: [
      {
        type: 'paragraph',
        text:
          'Visibility reports are often presented as polished percentages. The hard question comes ' +
          'next: what exactly did the engine answer, which source was cited, and why did this row count? ' +
          'Provenance makes those questions answerable without asking a teammate to trust a dashboard.',
      },
      { type: 'heading', text: 'What a defensible score carries' },
      {
        type: 'list',
        items: [
          'The prompt and project context used for the observation.',
          'The persisted answer and provider attempt that supplied the evidence.',
          'The deterministic analysis and rule versions that produced the derived fields.',
          'The coverage, limitations, and comparison boundary for the aggregate.',
        ],
      },
      { type: 'heading', text: 'Versioning protects the meaning of change' },
      {
        type: 'paragraph',
        text:
          'When a score changes, there are several possible explanations: the engine answered ' +
          'differently, the prompt changed, the measured cohort changed, or an analysis rule changed. ' +
          'Persisted source and version references let an analyst tell those cases apart.',
      },
      { type: 'heading', text: 'Unknown is better than a made-up zero' },
      {
        type: 'paragraph',
        text:
          'A provider outage, missing configuration, or partial crawl is not the same as an observed ' +
          'zero. A trustworthy report names the state it has and leaves an unmeasured result unqualified. ' +
          'That is more useful for decisions and more honest in an executive review.',
      },
      { type: 'heading', text: 'Make the trail useful to the next person' },
      {
        type: 'paragraph',
        text:
          'The goal is not to expose implementation detail for its own sake. It is to let a marketer, ' +
          'analyst, or security reviewer move from a finding to its source, understand the boundary, ' +
          'and decide what to do next without rebuilding the run from memory.',
      },
    ],
  },
  {
    slug: 'byok-ai-visibility-measurement-explained',
    title: 'BYOK AI visibility measurement, explained',
    excerpt:
      'What using your own provider keys changes — and what it does not — when you run answer-engine ' +
      'audits and content workflows.',
    tags: ['Operations', 'BYOK'],
    body: [
      {
        type: 'paragraph',
        text:
          'Bring-your-own-key (BYOK) means the provider account used for an audit belongs to your team. ' +
          'It changes the credential and billing boundary; it does not change the measurement contract. ' +
          'Prompts, responses, evidence, and derived results still belong to the configured workspace.',
      },
      { type: 'heading', text: 'What stays in your control' },
      {
        type: 'list',
        items: [
          'Provider account and usage billing remain with your provider.',
          'Credentials are encrypted at rest and resolved only when execution needs them.',
          'Keys are not returned in API responses or logged in clear text.',
          'You choose when an audit or schedule runs because provider calls have a cost.',
        ],
      },
      { type: 'heading', text: 'What the platform records' },
      {
        type: 'paragraph',
        text:
          'A run records the approved engine route, prompt context, provider attempt, and response ' +
          'evidence needed to explain the result. The supported direct answer-engine routes are ' +
          'ChatGPT, Gemini, and Claude; availability still depends on the provider configuration and ' +
          'the limits of the account you connect.',
      },
      { type: 'heading', text: 'Why the boundary matters' },
      {
        type: 'paragraph',
        text:
          'Keeping provider credentials separate from derived evidence makes both sides clearer. Your ' +
          'team controls the account and the run decision; the workspace retains the evidence trail ' +
          'needed to compare observations, inspect citations, and choose the next action.',
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
