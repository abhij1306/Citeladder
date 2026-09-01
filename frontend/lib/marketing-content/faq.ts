/**
 * FAQ content for /faq, aligned to the governed product loop in
 * docs/architecture.md.
 *
 * Answers describe the platform's architecture and guarantees at the vision
 * level; commercial answers follow lib/marketing-content/pricing.ts, the single
 * source for every published price and quota. Keep answers short and specific,
 * and never invent numbers, customers, or certainty.
 */

type FaqItem = {
  q: string;
  a: string;
};

export type FaqGroup = {
  heading: string;
  items: readonly FaqItem[];
};

function faqItem(q: string, a: string): FaqItem {
  return { q, a };
}

export const FAQ_GROUPS: readonly FaqGroup[] = [
  {
    heading: 'Platform',
    items: [
      faqItem(
        'What is CiteLadder?',
        `CiteLadder is an evidence-grounded growth-intelligence platform for AI search visibility. It connects owned-site and demand evidence, ranks the next action, and tracks observed mention and citation share under comparable conditions.`,
      ),
      faqItem(
        'How is the product organized?',
        `Five stations form one loop: Overview, Connect, Analyze, Act, and Track. Site Health, Content Intelligence, Demand Intelligence, and the bounded Growth Agent retain clear ownership behind those stations. Improve / Verify is the transition after you declare a change, not a separate workspace.`,
      ),
      faqItem(
        'How does the growth loop work?',
        `Connect evidence, analyze and prioritize gaps, declare an implemented action, observe later crawl or audit evidence, and track comparable outcomes. Verification reports what was observed afterwards; it does not claim causality.`,
      ),
      faqItem(
        'What is AEO, and how does CiteLadder support it?',
        `AEO means answer engine optimization: making your organization, pages, and claims easier for answer engines to understand and cite. CiteLadder checks page structure and evidence, then measures observed mentions and citations in ChatGPT, Gemini, and Claude under a versioned prompt portfolio.`,
      ),
      faqItem(
        'How does AEO relate to SEO?',
        `SEO helps people find and use your site in search. AEO adds the question of how answer engines interpret and reference that same evidence. CiteLadder brings site health, Google Search Console and GA4 signals, content work, and AI visibility into one connected workflow.`,
      ),
      faqItem(
        'Does CiteLadder measure AI visibility?',
        `Yes. AI Visibility is the Track station. CiteLadder observes how answer engines mention and cite your brand and competitors and traces every metric to persisted responses under a versioned prompt portfolio.`,
      ),
      faqItem(
        'Can CiteLadder create content?',
        `Content Intelligence turns a detected gap into an evidence-grounded brief, draft, and schema. Nothing is published automatically. Claims the draft cannot support from your project facts are flagged before you save, and saving is your decision.`,
      ),
      faqItem(
        'Which analytics sources can I connect?',
        `Demand Intelligence connects Google Search Console and GA4 so query and behavioral evidence sit beside your owned-page knowledge, and the work is prioritized by the demand that actually exists.`,
      ),
      faqItem(
        'What do I actually have to do?',
        `You make the product decisions that matter: save a piece of content, and run or schedule an audit. There is no approval queue or review inbox. The evidence work between those decisions is shown with its source, status, and limitations.`,
      ),
      faqItem(
        'What does "evidence-grounded" mean concretely?',
        `Every derived number opens the artifact it came from — the crawl, the imported row, or the engine answer, stored as it was observed. A claim with no resolvable source does not render as a conclusion. Scores show their coverage beside them rather than being rescaled over whatever happened to be measurable, because missing evidence usually marks a weakness rather than a neutral gap.`,
      ),
      faqItem(
        'What does CiteLadder not claim?',
        `It does not claim that a change caused a ranking, traffic, or revenue outcome. Verification is descriptive: it recrawls and reports what is observed afterwards. Aggregate correlations are not presented as causal, and where a signal is unavailable, not configured, or genuinely zero, those three are shown as different states rather than one empty chart.`,
      ),
    ],
  },
  {
    heading: 'Site Health',
    items: [
      faqItem(
        'What does Site Health analyze?',
        `Site Health safely crawls your website, records the acquired page as evidence, classifies its structural purpose, and applies deterministic checks suited to that page type. It persists scores, issues, architecture snapshots, changes, and prioritized opportunities so every result remains inspectable.`,
      ),
      faqItem(
        'How does CiteLadder decide which checks apply to a page?',
        `Classification uses observable evidence such as the URL path, headings, visible content, forms, links, delivery signals, and structured data. The resulting page type selects the relevant checklist and schema contract; structured data is one signal and never certifies its own page type.`,
      ),
      faqItem(
        'What happens when a page cannot be classified confidently?',
        `The page is classified as other rather than forced into the wrong type. General checks can still run, while page-type-specific rules stay out of scoring until the evidence supports a reliable classification.`,
      ),
    ],
  },
  {
    heading: 'Data & security',
    items: [
      faqItem(
        'How is my data isolated?',
        `Every customer fact is scoped to its workspace and project and never crosses workspaces. Product rules and analyzers are versioned independently so persisted results retain their source and can be interpreted in context.`,
      ),
      faqItem(
        'Can I see the evidence behind a recommendation?',
        `Yes. Every recommendation carries a typed evidence chain back to the crawl, integration import, or answer that produced it. Later observations append to the record; they do not rewrite earlier evidence.`,
      ),
      faqItem(
        'Does anything publish or change automatically?',
        `No. Saving content and running or scheduling an audit are your decisions, and both are enforced at the API, not just in the interface. Everything in between — crawling, classification, gap detection, prioritization — runs without asking, and the result is shown with the evidence behind it.`,
      ),
      faqItem(
        'Do I need my own API keys?',
        `Model calls run on your own provider keys, billed to your provider accounts at their rates and never marked up. Provider secrets are encrypted at rest and resolved only at execution time — never returned, logged, or placed in a prompt.`,
      ),
    ],
  },
  {
    heading: 'Account & billing',
    items: [
      faqItem(
        'How much does CiteLadder cost?',
        `Self-serve plans are published on /pricing, priced for your billing country; Enterprise is a custom, sales-assisted agreement. India is charged in INR with GST added; international cards are charged in USD. Because model calls run on your own provider keys, that usage is billed by your provider at their rates and is never marked up by us.`,
      ),
      faqItem(
        'Do you mark up model usage?',
        `No. Model usage bills straight to your provider accounts and never passes through us. CiteLadder charges for the workspace, the intelligence, and the evidence — the current plan prices are on /pricing.`,
      ),
      faqItem(
        'What do I need to get started?',
        `A plan from /pricing and your own AI provider key — the key is what runs the measurement and generation on your behalf.`,
      ),
      faqItem(
        'Can I change plan later?',
        `Yes — plans change at any time and take effect on the next billing period. Your projects, evidence, and exports are unaffected by a plan change.`,
      ),
    ],
  },
];
