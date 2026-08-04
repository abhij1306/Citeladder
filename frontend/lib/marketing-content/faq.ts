/**
 * FAQ content for /faq — four groups matching the approved mockup.
 *
 * Product answers are grounded in README.md and docs/site-health.md;
 * commercial answers follow lib/marketing-content/pricing.ts, which is the
 * single source for every published price and quota.
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
    heading: 'Product',
    items: [
      {
        q: 'What is CiteLadder?',
        a:
          'CiteLadder is an AI visibility and site intelligence platform. It runs ' +
          'repeatable audits of your brand across ChatGPT, Gemini, and Claude using your own ' +
          'provider keys, scores the results deterministically, and keeps the persisted evidence ' +
          'behind every number. A built-in, security-bounded crawler also audits your site’s ' +
          'Web Fundamentals and AEO health, with grouped issues and remediation guidance — so you can ' +
          'measure the answers and improve the pages they rely on.',
      },
      {
        q: 'Which answer engines does CiteLadder cover?',
        a:
          'ChatGPT, Gemini, and Claude. One audit runs the same prompts across all three, side ' +
          'by side, with comparable scores. Each engine runs through exactly one approved ' +
          'transport, and every run records all three identities: logical engine, transport ' +
          'provider, and exact transport model.',
      },
      {
        q: 'What does deterministic scoring mean?',
        a:
          'Headline metrics — mentions, citations, share of voice — are computed from persisted ' +
          'evidence with explicit, versioned rules: the same data always produces the same score. ' +
          'Every projection carries its analyzer and scoring-rule versions, so any number can be ' +
          'traced back to the exact run and rule set that produced it. Metrics that aren’t ' +
          'supported stay null and render as — instead of a fabricated zero.',
      },
      {
        q: 'What is query fanout?',
        a:
          'When an answer engine grounds its response, it expands your prompt into generated ' +
          'search queries — the query fanout. Those generated queries decide which pages get ' +
          'retrieved and cited. CiteLadder persists the fanout as evidence, so you can see which ' +
          'generated searches shaped the answer.',
      },
      {
        q: 'What is share of voice?',
        a:
          'Share of voice measures how present your brand is in engine responses compared with ' +
          'the competitors you track. It is computed from persisted runs and tracked over time, ' +
          'engine by engine, in the visibility workspace.',
      },
      {
        q: 'How much setup does a first audit need?',
        a:
          'A brand name, a website and a country. From those, CiteLadder suggests competitors, ' +
          'the domains you own and a starting prompt library, all editable before the first run.',
      },
      {
        q: 'Which analytics sources can I connect?',
        a:
          'Google Search Console, GA4, Bing Webmaster Tools and Shopify. Search Console and ' +
          'GA4 share one Google consent; Bing rides a Microsoft grant. Syncs run on a schedule, ' +
          'on demand, or as a backfill, and organic plus AI-referred sessions are folded into a ' +
          'single trailing window — 28 days by default.',
      },
      {
        q: 'Does CiteLadder connect AI visibility to real traffic?',
        a:
          'It reports a Pearson coefficient between day-aligned cross-engine visibility and ' +
          'AI-referral sessions, alongside the sample size. It is descriptive, not a forecast, ' +
          'and when there is not enough overlapping data the surface says “insufficient data” ' +
          'instead of printing a number. AI referrals are classified by deterministic rules — ' +
          'referrer, then UTM, then user agent — with no model in the loop, and sources such as ' +
          'Perplexity, Microsoft Copilot and Google AI Overview are recognised as referral ' +
          'sources even though they are not audited engines.',
      },
      {
        q: 'Can CiteLadder measure product-level visibility?',
        a:
          'Yes. A deterministic sibling analyzer pass scores your catalog from the same ' +
          'persisted responses — product share of voice, rank distribution per engine, whether ' +
          'the quoted price matches your own catalog, which competitor products appear ' +
          'alongside yours, and where the answer sends the shopper next. Catalog and orders ' +
          'arrive from Shopify or a CSV import.',
      },
      {
        q: 'Can I see revenue attributed to AI answers?',
        a:
          'Two independent views, deliberately not merged: GA4 platform-attributed revenue, and ' +
          'revenue from Shopify orders whose referrer was an AI source. They are shown side by ' +
          'side as a cross-check, always partitioned by currency — CiteLadder never converts or ' +
          'sums across currencies to manufacture one headline number.',
      },
      {
        q: 'Can CiteLadder draft content, and what is it grounded in?',
        a:
          'Yes — drafts are grounded in a snapshot of your own crawled pages, passed as data ' +
          'rather than as instructions, so page text can never rewrite the prompt. Each draft ' +
          'records whether that site context was available, and the generator version that ' +
          'produced it.',
      },
    ],
  },
  {
    heading: 'Privacy & keys',
    items: [
      {
        q: 'Do I need my own API keys?',
        a:
          'Yes — audits are BYOK. You connect your own OpenAI, Anthropic, and Google keys, pay ' +
          'your providers directly, and keep full control over usage and spend. CiteLadder never ' +
          'resells model calls.',
      },
      {
        q: 'How are my keys stored?',
        a:
          'Provider secrets are Fernet-encrypted at rest and resolved only at execution time. A ' +
          'key is never returned in an API response, never logged, and never sent as part of a ' +
          'prompt.',
      },
      {
        q: 'What data does the site crawler keep?',
        a:
          'The first-party crawler is SSRF-bounded and resource-capped, and raw fetched HTML is ' +
          'never retained. Site Health stores delivery facts, normalized page facts, evidence, ' +
          'links, and issue history — not your page source.',
      },
    ],
  },
  {
    heading: 'Site health',
    items: [
      {
        q: 'Free sample vs Paid monitoring — what’s the difference?',
        a:
          'Free runs a deterministic, seeded sample crawl that is read-only: a sample set is ' +
          'auto-selected and analyzed, and the discovered full-site total is never disclosed. ' +
          'Paid runs the full progressive inventory and lets you pick a quota-limited set of ' +
          'URLs to monitor — that set is analyzed and dashboarded.',
      },
      {
        q: 'What do the Web Fundamentals and AEO scores mean?',
        a:
          'Each analyzed page is scored against 33 deterministic rules in 8 categories — ' +
          'indexability, content, metadata, structured data, citability, performance, security ' +
          'and links. Web Fundamentals and AEO are weighted 50/50 into the combined score, every rule ' +
          'outcome is inspectable, and a missing or failed score renders as — rather than a ' +
          'fabricated zero. Pages are classified into one of nine page types, and the expected ' +
          'schema and minimum depth are judged per type rather than by one global rule.',
      },
      {
        q: 'Does CiteLadder check whether AI crawlers can reach my site?',
        a:
          'Yes. The crawler records the allow or block stance your robots rules take toward ' +
          'GPTBot, ClaudeBot, PerplexityBot and Google-Extended, and flags a blocked stance as ' +
          'an issue. It also checks whether you publish /llms.txt — the plain-text summary ' +
          'answer engines read — and detects bot-block responses, escalating from a plain HTTP ' +
          'fetch to an impersonated client when a block signature appears.',
      },
      {
        q: 'How does issue remediation work?',
        a:
          'Issues are grouped by severity and dimension across your pages, and each group ' +
          'carries remediation guidance plus navigation into the affected pages. Per-URL ' +
          'diagnostics show delivery facts, normalized page facts, evidence, links, and issue ' +
          'history. Authenticated CSV and Markdown exports, scoped to your workspace, let you ' +
          'hand the work to whoever fixes it.',
      },
    ],
  },
  {
    heading: 'Account & billing',
    items: [
      {
        q: 'How much does CiteLadder cost?',
        // No amount here on purpose: prices are region-resolved per visitor
        // and published by the catalog, so a number baked into this answer
        // would be wrong for most readers and stale for the rest.
        a:
          'Self-serve plans are published on /pricing, priced for your billing country; ' +
          'Enterprise is a custom sales-assisted agreement. India is charged in INR with GST ' +
          'added. International cards are charged in USD and the card issuer may convert that ' +
          'amount. Because audits run on your own provider keys, model usage is billed by your ' +
          'provider at their rates and is never marked up by us.',
      },
      {
        q: 'Do you mark up model usage?',
        a:
          'No. Audits execute on your own provider keys, so ChatGPT, Gemini and Claude usage ' +
          'is billed to your own provider accounts at their rates and never passes through us. ' +
          'CiteLadder charges for the workspace, the monitoring and the evidence; the current ' +
          'plan prices are on /pricing.',
      },
      {
        q: 'What do I need before I can run an audit?',
        // Replaces the retired "no card needed" answer rather than swapping
        // one unbacked promise for another: there is no free tier and no
        // trial in this release, so the honest answer is what is required.
        a:
          'A plan from /pricing and your own AI provider key — audits execute on your keys, so ' +
          'the key is what actually runs the measurement.',
      },
      {
        q: 'Can I change plan later?',
        a:
          'Yes — plans change at any time and take effect on the next billing period. Your runs, ' +
          'evidence and exports are unaffected by a plan change.',
      },
    ],
  },
];
