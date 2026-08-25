/**
 * Landing-page copy for the public marketing surface.
 *
 * Structure and copy follow the governed product loop. Durable Site, Content,
 * Demand, and Agent capabilities sit behind user-facing loop
 * stations. Sections carry icons and the prototype's fuller detail (a four-step
 * loop, use-case item lists, and a security ledger). Only the hero tagline, the
 * product visual, and the type scale/weight are ours.
 *
 * Icons are named here as string keys and resolved to lucide components in the
 * section files (keeps this a pure data module).
 */

export type IconKey =
  | 'collect'
  | 'analyze'
  | 'improve'
  | 'verify'
  | 'education'
  | 'commerce'
  | 'services'
  | 'saas'
  | 'media'
  | 'finance'
  | 'isolation'
  | 'provenance'
  | 'correction'
  | 'versioned'
  | 'ask'
  | 'prove'
  | 'see';

export const LANDING_CONTENT = {
  hook: {
    eyebrow: 'Evidence-grounded AEO',
    // Retained tagline — the hook the site opens on.
    title: 'Your buyers stopped Googling you.',
    titleAccent: 'They ask AI instead.',
    body: 'Connect what your site proves with what people search for, act on the clearest gap, and track observed mention and citation share without causal overclaiming.',
    primaryCta: 'Book a demo',
    secondaryCta: 'See how it works',
  },

  // NOTE: the prototype's "Trusted by …" logo strip is intentionally omitted —
  // it named fictional customers, and fabricated endorsements must not ship on
  // the real site. Add a real customer/logo strip here when logos exist.

  shift: {
    kicker: 'The shift',
    title: 'Growth stopped being a guessing game.',
    facts: [
      {
        icon: 'ask' as IconKey,
        label: 'Ask',
        title: 'Buyers ask before they browse.',
        body: 'Shortlists now start inside an answer engine — and often end there.',
      },
      {
        icon: 'prove' as IconKey,
        label: 'Prove',
        title: 'Answers cite evidence, not opinions.',
        body: 'Either your pages prove the claim an engine needs, or a competitor’s do.',
      },
      {
        icon: 'see' as IconKey,
        label: 'See',
        title: 'You can’t fix what you can’t see.',
        body: 'Scattered tools hide the gap. One system of record makes it measurable.',
      },
    ],
  },

  seeIt: {
    kicker: 'The product',
    title: 'The whole system, in one workspace.',
    cta: 'Run this on your market',
  },

  workflow: {
    kicker: 'How it works',
    title: 'Evidence to improvement, in a closed loop.',
    lead: 'CiteLadder runs a continuous cycle. Every pass tightens the evidence, sharpens the next action, and verifies the last one.',
    steps: [
      {
        num: '01',
        icon: 'collect' as IconKey,
        label: 'Collect evidence',
        desc: 'Crawl pages, ingest Search Console and GA4, index documents, and measure AI visibility — all versioned and verifiable.',
      },
      {
        num: '02',
        icon: 'analyze' as IconKey,
        label: 'Analyze & prioritize',
        desc: 'Apply deterministic checks and measured signals. Score every gap by business impact. Rank the queue by evidence strength.',
      },
      {
        num: '03',
        icon: 'improve' as IconKey,
        label: 'Improve content',
        desc: 'Generate briefs, drafts, schema, and FAQs. Unsupported claims are flagged against your facts, and you decide what to save.',
      },
      {
        num: '04',
        icon: 'verify' as IconKey,
        label: 'Measure & verify',
        desc: 'Recrawl after publication. Confirm the improvement registered. Feed the result back to the evidence layer.',
      },
    ],
  },

  packs: {
    kicker: 'Use cases',
    title: 'Built around how your industry actually works.',
    lead: 'The same evidence loop adapts to different business models while page classification, checks, and provenance stay explicit.',
    items: [
      {
        icon: 'education' as IconKey,
        name: 'Education',
        points: [
          'Program and course page optimization',
          'Accreditation entity coverage',
          'Student FAQ gap detection',
          'Enrollment journey mapping',
        ],
      },
      {
        icon: 'commerce' as IconKey,
        name: 'Commerce',
        points: [
          'Product detail page completeness',
          'Category page gap analysis',
          'Support FAQ automation',
          'Shopping-assistant visibility',
        ],
      },
      {
        icon: 'services' as IconKey,
        name: 'Professional services',
        points: [
          'Service page role classification',
          'Case study and proof coverage',
          'Expert biography completeness',
          'Expertise, authority, trust signals',
        ],
      },
      {
        icon: 'saas' as IconKey,
        name: 'Enterprise SaaS',
        points: [
          'Landing and pricing intelligence',
          'Technical documentation coverage',
          'Changelog and release-note gaps',
          'Integration entity mapping',
        ],
      },
      {
        icon: 'media' as IconKey,
        name: 'Media & publishing',
        points: [
          'Article and author schema coverage',
          'Editorial FAQ and explainer gaps',
          'AI citation and summary visibility',
          'Content freshness monitoring',
        ],
      },
      {
        icon: 'finance' as IconKey,
        name: 'Financial services',
        points: [
          'Regulatory disclosure completeness',
          'Advisor profile and credential gaps',
          'Trust signal and review coverage',
          'Product assertion accuracy',
        ],
      },
    ],
  },

  trust: {
    kicker: 'Enterprise-grade',
    title: 'Built for regulated and security-conscious enterprises.',
    lead: 'CiteLadder keeps the record inspectable from the first crawl to the latest recommendation.',
    guarantees: [
      {
        icon: 'isolation' as IconKey,
        title: 'Data isolation',
        description: 'Every customer fact stays project-scoped and never crosses workspaces.',
      },
      {
        icon: 'provenance' as IconKey,
        title: 'Full provenance',
        description: 'Every recommendation links to the typed evidence chain behind it.',
      },
      {
        icon: 'correction' as IconKey,
        // NOT "durable corrections": EditableFact has no production caller and
        // no persistence path yet, and the site does not advertise capability
        // the product cannot keep (§9.1). Restore the stronger claim when
        // corrections are wired to a durable mutation.
        title: 'No silent rewrites',
        description: 'New observations append to the record instead of replacing earlier evidence.',
      },
      {
        icon: 'versioned' as IconKey,
        title: 'Versioned analysis',
        description:
          'Classifiers, rules, formulas, and source evidence stay versioned and inspectable.',
      },
    ],
  },

  cta: {
    kicker: 'Get started',
    title: 'Grow on evidence, not assumptions.',
    body: 'A working session on your category, your competitors, and the gaps buyers already see.',
    primaryCta: 'Book a demo',
    secondaryCta: 'See pricing',
  },
} as const;
