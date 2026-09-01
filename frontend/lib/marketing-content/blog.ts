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

function paragraph(text: string): BlogBlock {
  return { type: 'paragraph', text };
}

function heading(text: string): BlogBlock {
  return { type: 'heading', text };
}

function bulletList(...items: readonly string[]): BlogBlock {
  return { type: 'list', items };
}

type BlogSection = readonly [title: string, content: string | readonly string[]];

function outlinedArticle(intro: string, ...sections: readonly BlogSection[]): readonly BlogBlock[] {
  return [
    paragraph(intro),
    ...sections.flatMap(([title, content]) => [
      heading(title),
      typeof content === 'string' ? paragraph(content) : bulletList(...content),
    ]),
  ];
}

export const POSTS: readonly BlogPost[] = [
  {
    slug: 'how-we-measure-ai-visibility-deterministically',
    title: 'How to measure AI visibility with evidence you can audit',
    excerpt:
      'A practical explanation of answer-engine measurement: persist the answer, apply explicit ' +
      'rules, show coverage, and keep every score tied to the evidence that produced it.',
    tags: ['AI visibility', 'Measurement'],
    body: [
      paragraph(
        'AI visibility is not a single ranking position. It is an observation of what an answer ' +
          'engine says when a defined audience asks a defined question. A useful measurement ' +
          'therefore needs the prompt, the engine, the response, and the rules used to interpret it.',
      ),
      heading('Start with the answer, not a verdict'),
      paragraph(
        'The raw response is the primary evidence. Mentions, citations, recommendation presence, ' +
          'and observed share are derived from that persisted artifact with explicit rules. A model ' +
          'does not grade another model to create the headline number.',
      ),
      heading('Make the measurement reproducible'),
      paragraph(
        'A comparable run freezes the prompt portfolio, engine selection, and relevant analysis ' +
          'versions. When the result moves, the audit trail lets you separate a changed answer ' +
          'from a changed interpretation.',
      ),
      bulletList(
        'Persist the exact answer and its provider attempt before deriving metrics.',
        'Keep prompt, engine, repetition, and analysis context with each observation.',
        'Show coverage and limitations next to every aggregate, including unavailable and zero states.',
      ),
      heading('Treat coverage as part of the result'),
      paragraph(
        'A percentage without its denominator invites false confidence. CiteLadder keeps observed ' +
          'zero, unavailable, not configured, and incomplete coverage distinct, so a team can tell ' +
          'what was measured and what still needs evidence.',
      ),
      heading('Use the result to decide what to improve'),
      paragraph(
        'The measurement is a starting point for action, not proof of causality. Pair answer ' +
          'evidence with site health, demand signals, and the content changes your team chooses. ' +
          'Later audits report what was observed after the change without claiming that the change caused it.',
      ),
      paragraph(
        'That is the standard we use for AI visibility: a number is useful when a teammate can open ' +
          'it, inspect the answer behind it, understand its coverage, and explain how it was derived.',
      ),
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
      paragraph(
        'Answer-engine optimization starts before a prompt is run. If important pages are hard to ' +
          'discover, structurally unclear, or unsupported by visible facts, a citation report cannot ' +
          'tell you what to fix first. An audit connects those observations into one workflow.',
      ),
      heading('1. Establish the pages and facts you own'),
      paragraph(
        'Begin with a bounded crawl of the owned site. Record the fetched artifact, normalize the ' +
          'page facts, and classify each supported page by its structural purpose. A page without ' +
          'enough evidence stays unclassified rather than being forced into a generic verdict.',
      ),
      heading('2. Apply checks that fit the page'),
      paragraph(
        'A product page, article, FAQ, and organization page do not have the same job. Page-kind ' +
          'checks should test the signals that matter for that job: visible headings and content, ' +
          'links, metadata, delivery, and structured data. Structured data can support classification, ' +
          'but it cannot certify the schema being checked.',
      ),
      heading('3. Turn demand into a prompt portfolio'),
      paragraph(
        'Use search and journey evidence to define the questions your audience actually asks. Keep ' +
          'the portfolio explicit: each prompt has an intent, an audience, and a reason it belongs in ' +
          'the measurement. This makes later runs comparable instead of turning them into a random sample.',
      ),
      bulletList(
        'Connect owned pages, demand sources, and approved provider routes.',
        'Analyze structural gaps and answer-engine responses against the same project context.',
        'Prioritize an opportunity with its evidence, scope, and suggested content handoff.',
        'After publication, recrawl or rerun the same cohort and report the observation.',
      ),
      heading('4. Read citations as observations'),
      paragraph(
        'A citation shows that a source appeared in a particular response under particular ' +
          'conditions. It does not prove that the source caused a ranking, traffic, or revenue result. ' +
          'Keep that distinction visible when sharing an AEO report with stakeholders.',
      ),
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
      paragraph(
        'Visibility reports are often presented as polished percentages. The hard question comes ' +
          'next: what exactly did the engine answer, which source was cited, and why did this row count? ' +
          'Provenance makes those questions answerable without asking a teammate to trust a dashboard.',
      ),
      heading('What a defensible score carries'),
      bulletList(
        'The prompt and project context used for the observation.',
        'The persisted answer and provider attempt that supplied the evidence.',
        'The deterministic analysis and rule versions that produced the derived fields.',
        'The coverage, limitations, and comparison boundary for the aggregate.',
      ),
      heading('Versioning protects the meaning of change'),
      paragraph(
        'When a score changes, there are several possible explanations: the engine answered ' +
          'differently, the prompt changed, the measured cohort changed, or an analysis rule changed. ' +
          'Persisted source and version references let an analyst tell those cases apart.',
      ),
      heading('Unknown is better than a made-up zero'),
      paragraph(
        'A provider outage, missing configuration, or partial crawl is not the same as an observed ' +
          'zero. A trustworthy report names the state it has and leaves an unmeasured result unqualified. ' +
          'That is more useful for decisions and more honest in an executive review.',
      ),
      heading('Make the trail useful to the next person'),
      paragraph(
        'The goal is not to expose implementation detail for its own sake. It is to let a marketer, ' +
          'analyst, or security reviewer move from a finding to its source, understand the boundary, ' +
          'and decide what to do next without rebuilding the run from memory.',
      ),
    ],
  },
  {
    slug: 'byok-ai-visibility-measurement-explained',
    title: 'BYOK AI visibility measurement, explained',
    excerpt:
      'What using your own provider keys changes — and what it does not — when you run answer-engine ' +
      'audits and content workflows.',
    tags: ['Operations', 'BYOK'],
    body: outlinedArticle(
      'Bring-your-own-key (BYOK) means the provider account used for an audit belongs to your team. ' +
        'It changes the credential and billing boundary; it does not change the measurement contract. ' +
        'Prompts, responses, evidence, and derived results still belong to the configured workspace.',
      [
        'What stays in your control',
        [
          'Provider account and usage billing remain with your provider.',
          'Credentials are encrypted at rest and resolved only when execution needs them.',
          'Keys are not returned in API responses or logged in clear text.',
          'You choose when an audit or schedule runs because provider calls have a cost.',
        ],
      ],
      [
        'What the platform records',
        'A run records the approved engine route, prompt context, provider attempt, and response ' +
          'evidence needed to explain the result. The supported direct answer-engine routes are ' +
          'ChatGPT, Gemini, and Claude; availability still depends on the provider configuration and ' +
          'the limits of the account you connect.',
      ],
      [
        'Why the boundary matters',
        'Keeping provider credentials separate from derived evidence makes both sides clearer. Your ' +
          'team controls the account and the run decision; the workspace retains the evidence trail ' +
          'needed to compare observations, inspect citations, and choose the next action.',
      ],
    ),
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
