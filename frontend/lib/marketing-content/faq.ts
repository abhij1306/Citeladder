/**
 * FAQ content for /faq, aligned to the governed product loop in
 * docs/architecture.md.
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
        a: `CiteLadder is an evidence-grounded growth-intelligence platform. It connects owned-site and demand evidence, ranks the next action, and tracks observed mention and citation share under comparable conditions.`,
      },
      {
        q: 'How is the product organized?',
        a: `Five stations form one loop: Connect, Analyze, Act, Improve / Verify, and Track. Site Health, Content, Demand, Opportunities, and the bounded Growth Agent retain clear ownership behind those stations.`,
      },
      {
        q: 'How does the growth loop work?',
        a: `Connect evidence, analyze and prioritize gaps, explicitly declare an implemented action, observe later crawl or audit evidence, and track comparable outcomes. Verification reports observation, never causality.`,
      },
      {
        q: 'Does CiteLadder measure AI visibility?',
        a: `Yes. AI Visibility is the Track station. CiteLadder observes how answer engines mention and cite your brand and competitors and traces every metric to persisted responses under a versioned prompt portfolio.`,
      },
      {
        q: 'Can CiteLadder create content?',
        a: `Content Intelligence turns a detected gap into an evidence-grounded brief, draft, and schema. Nothing is published automatically. Claims the draft cannot support from your project facts are flagged before you save, and saving is your decision.`,
      },
      {
        q: 'Which analytics sources can I connect?',
        a: `Demand Intelligence connects Google Search Console and GA4 so query and behavioral evidence sit beside your owned-page knowledge, and the work is prioritized by the demand that actually exists.`,
      },
      {
        q: 'What do I actually have to do?',
        a: `You are asked to decide exactly twice: save a piece of content, and run or schedule an audit. There is no approval queue and no review inbox. Everything in between runs without asking, and the result is shown with the evidence behind it.`,
      },
      {
        q: 'What does "evidence-grounded" mean concretely?',
        a: `Every derived number opens the artifact it came from — the crawl, the imported row, or the engine answer, stored as it was observed. A claim with no resolvable source does not render as a conclusion. Scores show their coverage beside them rather than being rescaled over whatever happened to be measurable, because missing evidence usually marks a weakness rather than a neutral gap.`,
      },
      {
        q: 'What does CiteLadder not claim?',
        a: `It does not claim that a change caused a ranking, traffic, or revenue outcome. Verification is descriptive: it recrawls and reports what is observed afterwards. Aggregate correlations are not presented as causal, and where a signal is unavailable, not configured, or genuinely zero, those three are shown as different states rather than one empty chart.`,
      },
    ],
  },
  {
    heading: 'Industry packs',
    items: [
      {
        q: 'What is an industry pack?',
        a: `A versioned pack encodes the page roles, gap-detection rules, and schema expectations of a specific business model, so classification and gap-finding are judged the way your industry actually works rather than by one generic rule. A project runs one primary pack plus the reviewed capabilities it needs, and every finding records the pack ID and version that produced it.`,
      },
      {
        q: 'Which industries are covered?',
        a: `CiteLadder includes industry packs for education, commerce, professional services, enterprise SaaS, media, and financial services. Each pack defines the page roles, gap rules, and schema expectations used to evaluate that business model, and every finding records the pack and version that produced it.`,
      },
      {
        q: 'Do packs share my data with other customers?',
        a: `No. Industry knowledge is shared and versioned across the platform; your customer facts are not. A pack carries rules and expectations, never another company’s data.`,
      },
    ],
  },
  {
    heading: 'Data & security',
    items: [
      {
        q: 'How is my data isolated?',
        a: `Every customer fact is scoped to its project and never crosses workspaces. Shared industry packs are the only thing versioned across the platform — customer data never is.`,
      },
      {
        q: 'Can I see the evidence behind a recommendation?',
        a: `Yes. Every recommendation carries a typed evidence chain back to the crawl, integration import, or answer that produced it. A later observation never rewrites earlier evidence.`,
      },
      {
        q: 'Does anything publish or change automatically?',
        a: `No. Saving content and running or scheduling an audit are your decisions, and both are enforced at the API, not just in the interface. Everything in between — crawling, classification, gap detection, prioritization — runs without asking, and the result is shown with the evidence behind it.`,
      },
      {
        q: 'Do I need my own API keys?',
        a: `Model calls run on your own provider keys, billed to your provider accounts at their rates and never marked up. Provider secrets are encrypted at rest and resolved only at execution time — never returned, logged, or placed in a prompt.`,
      },
    ],
  },
  {
    heading: 'Account & billing',
    items: [
      {
        q: 'How much does CiteLadder cost?',
        a: `Self-serve plans are published on /pricing, priced for your billing country; Enterprise is a custom, sales-assisted agreement. India is charged in INR with GST added; international cards are charged in USD. Because model calls run on your own provider keys, that usage is billed by your provider at their rates and is never marked up by us.`,
      },
      {
        q: 'Do you mark up model usage?',
        a: `No. Model usage bills straight to your provider accounts and never passes through us. CiteLadder charges for the workspace, the intelligence, and the evidence — the current plan prices are on /pricing.`,
      },
      {
        q: 'What do I need to get started?',
        a: `A plan from /pricing and your own AI provider key — the key is what runs the measurement and generation on your behalf.`,
      },
      {
        q: 'Can I change plan later?',
        a: `Yes — plans change at any time and take effect on the next billing period. Your projects, evidence, and exports are unaffected by a plan change.`,
      },
    ],
  },
];
