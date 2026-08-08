/**
 * Landing-page copy for the public marketing surface.
 *
 * Structure and copy follow the approved prototype: a growth-intelligence
 * platform built from Site, Content, and Demand intelligence with a Growth Agent
 * on top. Sections carry icons and the prototype's fuller detail (module feature
 * lists, a four-step loop, industry-pack item lists, a security ledger). Only the
 * hero tagline, the product visual, and the type scale/weight are ours.
 *
 * Icons are named here as string keys and resolved to lucide components in the
 * section files (keeps this a pure data module).
 */

export type IconKey =
  | 'site'
  | 'content'
  | 'demand'
  | 'agent'
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
    eyebrow: 'Growth intelligence platform',
    // Retained tagline — the hook the site opens on.
    title: 'Your buyers stopped Googling you.',
    titleAccent: 'They ask AI instead.',
    body: 'CiteLadder unifies site, content, and demand intelligence with a growth agent that finds the gaps, prioritizes the work, and verifies every improvement against evidence.',
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

  platform: {
    kicker: 'Product architecture',
    title: 'Four intelligence layers, one growth system.',
    lead: 'Every layer verifies its work before passing results to the next. Evidence flows up, actions flow down, and the Growth Agent orchestrates everything.',
    // The four-across summary row.
    summary: [
      {
        icon: 'site' as IconKey,
        name: 'Site Intelligence',
        desc: 'Crawl, classify, and index every page and asset.',
      },
      {
        icon: 'content' as IconKey,
        name: 'Content Intelligence',
        desc: 'Detect gaps, draft briefs, generate and verify content.',
      },
      {
        icon: 'demand' as IconKey,
        name: 'Demand Intelligence',
        desc: 'GSC, GA4, AI visibility, and journey signals unified.',
      },
      {
        icon: 'agent' as IconKey,
        name: 'Growth Agent',
        desc: 'Bounded orchestration you can inspect and correct.',
      },
    ],
    // The detailed module cards.
    modules: [
      {
        num: '01',
        icon: 'site' as IconKey,
        title: 'Site Intelligence',
        description:
          'Crawls and understands every page and document, builds verified knowledge, detects industry-specific gaps, and confirms changes after every recrawl.',
        features: [
          'Automated crawl and page-role classification',
          'Industry-specific gap detection rules',
          'Recrawl verification after changes',
          'Versioned working-knowledge store',
        ],
      },
      {
        num: '02',
        icon: 'content' as IconKey,
        title: 'Content Intelligence',
        description:
          'Turns detected gaps into strategies, briefs, FAQs, drafts, and post-publication verification. Every claim is checked against your project facts before you save.',
        features: [
          'Evidence-grounded brief generation',
          'FAQPage JSON-LD schema automation',
          'Unsupported claims flagged against your facts',
          'Post-publication verification pass',
        ],
      },
      {
        num: '03',
        icon: 'demand' as IconKey,
        title: 'Demand Intelligence',
        description:
          'Connects Search Console, GA4, AI visibility, and customer journeys so you always prioritize the action with the highest actual impact.',
        features: [
          'Search Console + GA4 integration',
          'AI visibility across answer engines',
          'Customer-journey mapping',
          'Organic and AI signal unification',
        ],
      },
      {
        num: '04',
        icon: 'agent' as IconKey,
        title: 'Growth Agent',
        description:
          'An orchestrator that explains every recommendation. Bounded tasks, typed tools, selective context, and reproducible provenance throughout.',
        features: [
          'Two decisions: save content, and run an audit',
          'Typed tool calls with an audit log',
          'Versioned industry packs',
          'Project-scoped facts, never shared',
        ],
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
        desc: 'Apply industry-pack rules. Score every gap by business impact. Rank the queue by evidence strength.',
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
    // Fourteen foundation drafts do not support "every growth team"; the claim
    // is scoped to the composition model that actually ships.
    title: 'Built around how your industry actually works.',
    lead: 'Each project runs one primary industry pack plus the reviewed capabilities it needs — page roles, gap rules, and schema expectations, versioned together.',
    items: [
      {
        icon: 'education' as IconKey,
        name: 'Education',
        // "Reviewed" read as an authoritative production finding. These packs
        // are ready for controlled shadow evaluation, not for citing as fact.
        status: 'Education pack · Validated candidate',
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
        status: 'Commerce pack · Validated candidate',
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
        status: 'Services pack · Foundation draft',
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
        status: 'SaaS pack · Foundation draft',
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
        status: 'Media pack · Foundation draft',
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
        status: 'Finance pack · Foundation draft',
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
    lead: 'Customer data stays workspace-scoped and project-scoped. Industry knowledge packs are versioned and shared across the platform — customer facts never are.',
    features: [
      {
        icon: 'isolation' as IconKey,
        title: 'Data isolation',
        sub: 'Project-scoped, never cross-contaminated',
      },
      {
        icon: 'provenance' as IconKey,
        title: 'Full provenance',
        sub: 'Every recommendation carries its evidence chain',
      },
      {
        icon: 'correction' as IconKey,
        title: 'Durable corrections',
        sub: 'Correct any derived fact in place; it survives recompute',
      },
      {
        icon: 'versioned' as IconKey,
        title: 'Versioned knowledge',
        sub: 'Shared packs are release-managed, not silent',
      },
    ],
    ledger: [
      { label: 'Customer data isolation', value: 'Project-scoped, never shared across workspaces' },
      { label: 'Agent provenance', value: 'Every recommendation includes a typed evidence chain' },
      {
        label: 'Corrections',
        value: 'Any derived fact is editable in place, attributable, and withdrawable',
      },
      {
        label: 'Industry pack versioning',
        value: 'Shared knowledge is versioned and release-managed',
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
