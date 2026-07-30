/**
 * Audience-segment content for `/solutions`.
 *
 * Copy is carried over verbatim from the approved marketing content audit —
 * these are the pains each team actually reports and the capabilities that
 * answer them. `scene` selects which evidence panel renders beside the copy;
 * the panels show the SHAPE of a surface (rows, bars, chips) and never an
 * invented customer result.
 */
export type SolutionScene = 'share' | 'health' | 'sample' | 'commerce' | 'citations';

export type SolutionSegment = {
  id: string;
  label: string;
  eyebrow: string;
  title: string;
  pains: readonly string[];
  mappings: readonly string[];
  cta: string;
  scene: SolutionScene;
};

export const SOLUTIONS_HERO = {
  eyebrow: 'Solutions',
  title: 'One evidence layer for',
  accent: 'every team behind the brand.',
  lead: 'Searchify measures how answer engines talk about you — giving every team re-checkable proof in its native format.',
} as const;

export const SOLUTION_SEGMENTS: readonly SolutionSegment[] = [
  {
    id: 'agencies',
    label: 'Agencies',
    eyebrow: 'For agencies',
    title: 'Show retainer ROI with evidence clients can independently verify.',
    pains: [
      'Screenshots fail to prove retainer value to demanding clients.',
      'AI visibility is missing from standard reporting dashboards.',
      'Every client tracks a distinct mix of engines and prompts.',
    ],
    mappings: [
      'Isolated multi-project workspaces per client with UUID scoping.',
      'Authenticated client evidence exports in CSV and Markdown.',
      'Competitor share-of-voice and citation benchmarking per market.',
      'Deterministic scores with full drill-down to raw engine runs.',
    ],
    cta: 'See agency workflow',
    scene: 'share',
  },
  {
    id: 'in-house',
    label: 'In-house teams',
    eyebrow: 'For in-house teams',
    title: 'Executive AI visibility metrics that hold up in board meetings.',
    pains: [
      'Leadership demands verified AI metrics, not ungrounded claims.',
      'Engine visibility shifts weekly without clear root cause.',
      'Technical and AEO fixes live scattered across legacy tools.',
    ],
    mappings: [
      'Multi-engine cross-run trend analysis with timeline controls.',
      '33 deterministic site-health rules weighted 50/50 for Tech & AEO.',
      'Per-URL page diagnostics, delivery history, and live issue logs.',
      'Automated Search Console and GA4 syncs with zero double-counting.',
    ],
    cta: 'See reporting surfaces',
    scene: 'health',
  },
  {
    id: 'founders',
    label: 'Founders',
    eyebrow: 'For founders',
    title: 'Know if AI engines recommend you before your prospects search.',
    pains: [
      'Buyers ask ChatGPT and Perplexity before visiting your site.',
      'Enterprise AEO platforms are overpriced for growing teams.',
      'You need transparent, verifiable scores instead of black boxes.',
    ],
    mappings: [
      'Instant sample Site Health crawl with seeded, capped URLs.',
      'BYOK model lets you run audits on your own API keys at cost.',
      'Verifiable scoring recomputed directly from persisted raw runs.',
      'Complete data provenance with cryptographic run verification.',
    ],
    cta: 'See first audit sample',
    scene: 'sample',
  },
  {
    id: 'commerce',
    label: 'Ecommerce',
    eyebrow: 'For ecommerce teams',
    title: 'Track product recommendations and price accuracy across AI engines.',
    pains: [
      'AI engines shortlist products, but your catalog SKUs are missing.',
      'Engines cite incorrect or outdated product prices to shoppers.',
      'Rival SKUs constantly displace your products in AI recommendations.',
    ],
    mappings: [
      'Product share-of-voice and rank distribution across top engines.',
      'Automated price accuracy validation matched against catalog data.',
      'Competitor co-placement and SKU displacement analytics.',
      'Direct Shopify catalog sync and fast CSV import workflows.',
    ],
    cta: 'See commerce workflow',
    scene: 'commerce',
  },
  {
    id: 'pr',
    label: 'PR & communications',
    eyebrow: 'For PR & comms',
    title: 'Prove your media narrative landed inside AI answer engines.',
    pains: [
      'Press coverage lands, but AI engines fail to cite your announcements.',
      'Competitors steal citations for key industry topics you pioneered.',
      'Impact reports measure reach and impressions, ignoring AI answers.',
    ],
    mappings: [
      'Real-time mention and citation tracking backed by raw engine output.',
      'Prompt-level citation ownership benchmarks against competitors.',
      'Query fanout tracking showing how prompts expand across engines.',
      'Stakeholder-ready CSV and Markdown exports for coverage reports.',
    ],
    cta: 'See citation evidence',
    scene: 'citations',
  },
];
