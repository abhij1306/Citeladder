/**
 * FAQ content for /faq — four groups aligned to the growth-intelligence
 * platform (see docs/architecture.md and the landing page).
 *
 * Answers describe the platform's architecture and guarantees at the vision
 * level; commercial answers follow lib/marketing-content/pricing.ts, the single
 * source for every published price and quota. Keep answers short and specific,
 * and never invent numbers, customers, or certainty.
 */

export type FaqItem = {
  q: string;
  a: string;
};

export type FaqGroup = {
  heading: string;
  items: readonly FaqItem[];
};

export const FAQ_GROUPS: readonly FaqGroup[] = [
  {
    heading: 'Platform',
    items: [
      {
        q: 'What is CiteLadder?',
        a:
          'CiteLadder is a growth-intelligence platform. It unifies site, content, and demand ' +
          'intelligence with a Growth Agent that finds gaps, ranks the work by impact, and ' +
          'verifies every improvement against evidence — so growth runs on proof, not guesswork.',
      },
      {
        q: 'What are the four intelligence layers?',
        a:
          'Site Intelligence crawls and understands your pages and documents. Content ' +
          'Intelligence turns detected gaps into briefs, drafts, and schema. Demand Intelligence ' +
          'unifies Search Console, GA4, and AI visibility. The Growth Agent orchestrates all ' +
          'three, explaining every recommendation and showing the evidence it used.',
      },
      {
        q: 'How does the growth loop work?',
        a:
          'A continuous cycle: collect evidence, analyze and prioritize the gaps, improve the ' +
          'content, then measure and verify. Every pass tightens the evidence, sharpens the next ' +
          'action, and confirms the last one before it counts as done.',
      },
      {
        q: 'Does CiteLadder measure AI visibility?',
        a:
          'Yes — it is part of Demand Intelligence. CiteLadder observes how the answer engines ' +
          'describe your brand and competitors, and traces every observation back to the answer ' +
          'it came from, so a score is always inspectable.',
      },
      {
        q: 'Can CiteLadder create content?',
        a:
          'Content Intelligence turns a detected gap into an evidence-grounded brief, draft, and ' +
          'schema. Nothing is published automatically. Claims the draft cannot support from your ' +
          'project facts are flagged before you save, and saving is your decision.',
      },
      {
        q: 'Which analytics sources can I connect?',
        a:
          'Demand Intelligence connects Google Search Console and GA4 so query and behavioral ' +
          'evidence sit beside your owned-page knowledge, and the work is prioritized by the ' +
          'demand that actually exists.',
      },
      {
        q: 'What do I actually have to do?',
        a:
          'You are asked to decide exactly twice: save a piece of content, and run or schedule ' +
          'an audit. There is no approval queue and no review inbox. Where something derived is ' +
          'wrong you correct it in place, wherever it is shown — the correction is attributed, ' +
          'reversible, and survives the next recompute.',
      },
      {
        q: 'What does "evidence-grounded" mean concretely?',
        a:
          'Every derived number opens the artifact it came from — the crawl, the imported row, ' +
          'or the engine answer, stored as it was observed. A claim with no resolvable source ' +
          'does not render as a conclusion. Scores show their coverage beside them rather than ' +
          'being rescaled over whatever happened to be measurable, because missing evidence ' +
          'usually marks a weakness rather than a neutral gap.',
      },
      {
        q: 'What does CiteLadder not claim?',
        a:
          'It does not claim that a change caused a ranking, traffic, or revenue outcome. ' +
          'Verification is descriptive: it recrawls and reports what is observed afterwards. ' +
          'Aggregate correlations are not presented as causal, and where a signal is ' +
          'unavailable, not configured, or genuinely zero, those three are shown as different ' +
          'states rather than one empty chart.',
      },
    ],
  },
  {
    heading: 'Industry packs',
    items: [
      {
        q: 'What is an industry pack?',
        a:
          'A versioned pack encodes the page roles, gap-detection rules, and schema expectations ' +
          'of a specific business model, so classification and gap-finding are judged the way ' +
          'your industry actually works rather than by one generic rule. A project runs one ' +
          'primary pack plus the reviewed capabilities it needs, and every finding records the ' +
          'pack ID and version that produced it.',
      },
      {
        q: 'Which industries are covered, and how mature is each?',
        a:
          'Packs carry one of two maturity labels. Education and Commerce are validated ' +
          'candidates — ready for controlled shadow evaluation, not yet authoritative production ' +
          'findings. Professional services, enterprise SaaS, media, and financial services are ' +
          'foundation drafts. We label these plainly because acting on a draft as though it were ' +
          'validated is the mistake the labels exist to prevent.',
      },
      {
        q: 'Do packs share my data with other customers?',
        a:
          'No. Industry knowledge is shared and versioned across the platform; your customer ' +
          'facts are not. A pack carries rules and expectations, never another company’s data.',
      },
    ],
  },
  {
    heading: 'Data & security',
    items: [
      {
        q: 'How is my data isolated?',
        a:
          'Every customer fact is scoped to its project and never crosses workspaces. Shared ' +
          'industry packs are the only thing versioned across the platform — customer data never is.',
      },
      {
        q: 'Can I see the evidence behind a recommendation?',
        a:
          'Yes. Every recommendation carries a typed evidence chain back to the crawl, ' +
          'integration import, or answer that produced it. A later observation never rewrites ' +
          'earlier evidence.',
      },
      {
        q: 'Does anything publish or change automatically?',
        a:
          'No. Saving content and running or scheduling an audit are your decisions, and both ' +
          'are enforced at the API, not just in the interface. Everything in between — crawling, ' +
          'classification, gap detection, prioritization — runs without asking, and the result ' +
          'is shown with the evidence behind it.',
      },
      {
        q: 'Do I need my own API keys?',
        a:
          'Model calls run on your own provider keys, billed to your provider accounts at their ' +
          'rates and never marked up. Provider secrets are encrypted at rest and resolved only at ' +
          'execution time — never returned, logged, or placed in a prompt.',
      },
    ],
  },
  {
    heading: 'Account & billing',
    items: [
      {
        q: 'How much does CiteLadder cost?',
        a:
          'Self-serve plans are published on /pricing, priced for your billing country; ' +
          'Enterprise is a custom, sales-assisted agreement. India is charged in INR with GST ' +
          'added; international cards are charged in USD. Because model calls run on your own ' +
          'provider keys, that usage is billed by your provider at their rates and is never ' +
          'marked up by us.',
      },
      {
        q: 'Do you mark up model usage?',
        a:
          'No. Model usage bills straight to your provider accounts and never passes through us. ' +
          'CiteLadder charges for the workspace, the intelligence, and the evidence — the current ' +
          'plan prices are on /pricing.',
      },
      {
        q: 'What do I need to get started?',
        a:
          'A plan from /pricing and your own AI provider key — the key is what runs the ' +
          'measurement and generation on your behalf.',
      },
      {
        q: 'Can I change plan later?',
        a:
          'Yes — plans change at any time and take effect on the next billing period. Your ' +
          'projects, evidence, and exports are unaffected by a plan change.',
      },
    ],
  },
];
