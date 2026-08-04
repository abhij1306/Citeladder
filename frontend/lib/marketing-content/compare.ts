/**
 * Competitor-comparison content for /compare and /compare/[competitor].
 *
 * Sourcing rule (internal — never rendered): every `citeladder` cell is
 * grounded in this repo's own source code; every `competitor` cell must be
 * confirmed first-party on the vendor's own site before it ships (sources and
 * review date noted per entry below). A row ships only when BOTH cells are
 * written — the table never renders a blank state, so an unsupported
 * dimension is simply omitted from that vendor's `rows`.
 *
 * Engine roster: CiteLadder coverage is the three engines the platform can
 * actually audit — ChatGPT, Gemini, and Claude, one approved transport each
 * (see backend `answer_engines/factory.py`) — one audit, one prompt set, your
 * own keys. Breadth is not our claim here; determinism and evidence are.
 * `lastReviewed` renders as a plain freshness badge; it is not a process
 * disclosure.
 */

export type ComparisonRow = {
  dimension: string;
  citeladder: string;
  competitor: string;
};

export type Competitor = {
  slug: string;
  name: string;
  /** One-line positioning, drawn from the vendor's own site copy. */
  tagline: string;
  /** ISO date of the last first-party review, e.g. '2026-08-01'. */
  lastReviewed: string;
  rows: readonly ComparisonRow[];
  /** Short editorial verdict, in our voice. */
  verdict: string;
  /** Honest fit: the customer profile the other tool genuinely serves well. */
  betterFit: string;
};

/**
 * Our side of every comparison — one entry per dimension, written once and
 * spread into whichever vendors have a cell to put beside it. Keyed by name
 * rather than ordered by index: a vendor may omit a dimension its public
 * material doesn't support, and the pairing has to survive any reordering.
 */
const OURS = {
  engines: {
    dimension: 'Engines covered',
    citeladder:
      'ChatGPT, Gemini, and Claude — one audit runs the same prompts across all three, ' +
      'side by side, on your own provider keys.',
  },
  scoring: {
    dimension: 'Scoring model',
    citeladder:
      'Deterministic and versioned — explicit analyzers and scoring rules over persisted ' +
      'evidence, with analyzer and scoring-rule versions attached to every projection. ' +
      'Same data, same score.',
  },
  evidence: {
    dimension: 'Evidence drill-down',
    citeladder:
      'Every headline metric links to the exact persisted run — raw response text, ' +
      'classified citations, and query-fanout evidence included.',
  },
  byok: {
    dimension: 'Bring your own keys',
    citeladder:
      'BYOK only — provider keys are Fernet-encrypted at rest, resolved only at execution ' +
      'time, and never returned in API responses, logged, or sent as part of a prompt.',
  },
  siteHealth: {
    dimension: 'Site health / AEO auditing',
    citeladder:
      'Built in — first-party SSRF-bounded crawler, Web Fundamentals + AEO scores, grouped issues ' +
      'with remediation, per-URL diagnostics, and workspace-scoped CSV/Markdown exports.',
  },
  provenance: {
    dimension: 'Provenance',
    citeladder:
      'Every derived number is stamped with the analyzer and rule version that produced ' +
      'it — scoring-v1, sh-rules-2, opp-formula-1 — so a score change is attributable to ' +
      'data or to code.',
  },
  // Staged, not yet shipped on any entry: no vendor publishes a comparable
  // site-health depth figure, and a row ships only when both cells are written.
  siteHealthDepth: {
    dimension: 'Site health depth',
    citeladder:
      '33 deterministic rules across 8 categories, Web Fundamentals and AEO weighted 50/50, ' +
      'plus AI-crawler stance detection and an /llms.txt check.',
  },
  price: {
    dimension: 'Price transparency',
    citeladder:
      'Published flat-rate plans: Free to start, $49/month before applicable tax for ' +
      'Paid, and a sales-assisted Enterprise agreement. Model usage is billed by your ' +
      'own provider at their rates and never marked up.',
  },
} as const satisfies Record<string, { dimension: string; citeladder: string }>;

/** "How we compare fairly" claims on the /compare index — all repo-grounded. */
export const FAIRNESS_POINTS = [
  'Deterministic scoring — versioned rules over persisted evidence',
  'BYOK — audits run on your own provider keys',
  'Evidence-first scoring — no LLM-as-judge',
] as const;

/** "CiteLadder at a glance" fact rows on the /compare index. */
export const FACT_ROWS = [
  { key: 'Engines', value: 'ChatGPT · Gemini · Claude — one audit' },
  { key: 'Scoring', value: 'Deterministic rules, versioned projections' },
  { key: 'Evidence', value: 'Every metric drills to the raw run' },
  { key: 'Keys', value: 'BYOK · Fernet-encrypted at rest' },
  { key: 'Site health', value: 'Web Fundamentals + AEO auditing built in' },
  { key: 'Provenance', value: 'Analyzer + rule version on every projection' },
] as const;

const REVIEWED_2026_08 = '2026-08-01';

/**
 * The published comparisons. Entries below are sourced from each vendor's
 * own homepage and pricing page as of `lastReviewed`:
 *  - Profound: tryprofound.com, tryprofound.com/pricing
 *  - Otterly AI: otterly.ai, otterly.ai/pricing
 *  - Scrunch AI: scrunchai.com, scrunchai.com/pricing
 *  - Peec AI: peec.ai, peec.ai/pricing
 * Dimensions whose cells the vendor's public material does not support are
 * omitted from that entry's rows rather than rendered blank.
 */
export const COMPETITORS: readonly Competitor[] = [
  {
    slug: 'profound',
    name: 'Profound',
    tagline: 'The full-stack marketing platform for AI search.',
    lastReviewed: REVIEWED_2026_08,
    rows: [
      {
        ...OURS.engines,
        competitor:
          'Starter tracks ChatGPT only; Growth tracks three answer engines; the full ' +
          'nine-platform roster is reserved for the Enterprise tier.',
      },
      {
        ...OURS.scoring,
        competitor:
          'Prompts run on their hosted platform on a daily cadence, with results analyzed ' +
          'for citations, sentiment, ranking, and competitive presence — methodology is ' +
          'not published.',
      },
      {
        ...OURS.evidence,
        competitor: 'Dashboards report share of voice, citations, sentiment, and rank per prompt.',
      },
      {
        ...OURS.byok,
        competitor:
          'Hosted service — the platform calls the answer engines under its own accounts; ' +
          'no BYOK on public plans.',
      },
      {
        ...OURS.siteHealth,
        competitor:
          'Not a built-in site-health audit. Agent Analytics tracks how AI crawlers reach ' +
          'your domain through CDN and server integrations (Cloudflare, Vercel, AWS, ' +
          'WordPress, and more in Enterprise).',
      },
      {
        ...OURS.provenance,
        competitor: 'No published versioning for scoring or analysis rules on the public site.',
      },
      {
        ...OURS.price,
        competitor:
          'Starter $99/mo (billed yearly, ChatGPT only, 50 prompts) and Growth $399/mo ' +
          '(three engines, 100 prompts, 3 seats); Enterprise is custom. Self-serve entry ' +
          'starts above a typical starter budget.',
      },
    ],
    verdict:
      'Profound is the enterprise heavyweight of this category: agent credits, ' +
      'prompt-demand data, agent analytics, and SSO — priced and packaged accordingly. ' +
      'We take the opposite trade: a narrower engine roster at a flat published price, a ' +
      'deterministic scoring model whose versions are stamped on every number, and the ' +
      'raw response evidence behind each one. Different buyers want different halves of ' +
      'that sentence.',
    betterFit:
      'A large marketing org that wants a hosted, all-in-one platform — content ' +
      'generation agents, prompt-volume demand data, SOC 2 and SSO on a custom contract — ' +
      'and has the budget and headcount to operate it.',
  },
  {
    slug: 'otterly-ai',
    name: 'Otterly AI',
    tagline: 'AI search monitoring, otterly simple.',
    lastReviewed: REVIEWED_2026_08,
    rows: [
      {
        ...OURS.engines,
        competitor:
          'Four engines are included in every plan — ChatGPT, Google AI Overviews, ' +
          'Perplexity, and Microsoft Copilot; Claude, Gemini, and AI Mode are paid add-ons ' +
          '(Claude is priced $29–$439/month depending on plan).',
      },
      {
        ...OURS.scoring,
        competitor:
          'Daily prompt tracking on their hosted platform with dashboards for coverage, ' +
          'average position, sentiment, and share of voice; scoring methodology is not ' +
          'published.',
      },
      {
        ...OURS.evidence,
        competitor:
          'Link-citation analysis shows which URLs AI answers reference, with reports ' +
          'and exports on top.',
      },
      {
        ...OURS.byok,
        competitor:
          'Hosted service — no BYOK. Otterly bills flat and notes you do not need any ' +
          'additional AI provider subscriptions.',
      },
      {
        ...OURS.siteHealth,
        competitor:
          'Includes a GEO audit built on content-crawlability checks, with monthly URL ' +
          'audit quotas by plan (1,000 on Lite, 5,000 on Standard, 10,000 on Premium).',
      },
      {
        ...OURS.provenance,
        competitor: 'Versioned scoring or analysis rules are not documented on the public site.',
      },
      {
        ...OURS.price,
        competitor:
          'Lite $29/mo (15 prompts, 1 workspace), Standard $189/mo (100 prompts), Premium ' +
          '$489/mo (400 prompts); extra engines are billed per engine, per plan.',
      },
    ],
    verdict:
      'Otterly AI is the approachable entry point: a low-priced Lite plan, ' +
      'unlimited team members on every tier, and a clean monitoring product. The cost ' +
      'model scales by prompts and per-engine add-ons — Claude alone can add more than ' +
      'the base plan — and the analysis layer is opaque. We sell the audit itself: three ' +
      'engines with no per-engine add-ons, deterministic scoring with versions on every ' +
      'number, and raw evidence one click below each.',
    betterFit:
      'A solo marketer or small team that wants to watch a handful of prompts on the ' +
      'biggest engines at the lowest possible entry price, with unlimited seats included.',
  },
  {
    slug: 'scrunch-ai',
    name: 'Scrunch AI',
    tagline: 'The AI customer experience platform — get your site AI-ready.',
    lastReviewed: REVIEWED_2026_08,
    rows: [
      {
        ...OURS.engines,
        competitor:
          'Tracks brand presence across AI answer engines within a broader agent-experience ' +
          'platform; the current public pages do not quote a per-plan engine roster.',
      },
      {
        ...OURS.scoring,
        competitor:
          'Monitoring with citations and insights inside a broader suite; the scoring ' +
          'methodology is not published.',
      },
      {
        ...OURS.evidence,
        competitor: 'Citations reporting shows where a brand is referenced in AI answers.',
      },
      {
        ...OURS.siteHealth,
        competitor:
          'Goes past auditing into serving: AXP detects AI agents at the edge and delivers ' +
          'AI-optimized content, alongside agent-traffic analytics and AI-consumption ' +
          'site maps.',
      },
      {
        ...OURS.provenance,
        competitor: 'No scoring or analysis versioning is published.',
      },
    ],
    verdict:
      'Scrunch AI and we agree on the diagnosis — AI agents are the new visitors — and ' +
      "diverge on the treatment. Scrunch's headline product sits on your edge and serves " +
      'AI-optimized content to agents, with monitoring around it. Ours is the measurement ' +
      'and evidence layer: a deterministic audit across ChatGPT, Gemini, and Claude, ' +
      'built-in site health and AEO rules, and every score traceable to a persisted raw ' +
      'answer.',
    betterFit:
      'A team that wants its site to actively serve optimized content to AI agents at ' +
      'the edge — infrastructure, not just measurement — and is ready to adopt a full ' +
      'agent-experience platform.',
  },
  {
    slug: 'peec-ai',
    name: 'Peec AI',
    tagline: 'AI search analytics for marketing teams.',
    lastReviewed: REVIEWED_2026_08,
    rows: [
      {
        ...OURS.engines,
        competitor:
          'Six platforms on every plan — ChatGPT, AI Mode, AI Overviews, Microsoft ' +
          'Copilot, Perplexity, and Gemini.',
      },
      {
        ...OURS.scoring,
        competitor:
          'Daily tracking across models with analytics on visibility, position, and ' +
          'sentiment; the scoring methodology is not published.',
      },
      {
        ...OURS.evidence,
        competitor:
          'Source and citation insights show which sites shape AI answers, with exports ' +
          'and a Looker Studio integration.',
      },
      {
        ...OURS.byok,
        competitor: 'Hosted analytics service; no BYOK model on public plans.',
      },
      {
        ...OURS.provenance,
        competitor: 'Public versioning of scoring or analysis rules is not documented.',
      },
    ],
    verdict:
      'Peec AI is a clean, well-liked analytics product with honest breadth: six named ' +
      'platforms on every tier and straightforward packaging for brands and agencies. ' +
      'Where we differ is depth of proof: our scores are deterministic and versioned, our ' +
      'site-health audit is built in rather than adjacent, and every metric resolves to ' +
      'the raw AI response underneath it.',
    betterFit:
      'SEO and content teams that want a simple, well-rated analytics dashboard across ' +
      'the major AI platforms, with agency-friendly reporting (Looker, API, MCP).',
  },
];
