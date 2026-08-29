/**
 * Legal entity + document content for marketing legal pages and the footer
 * strip. Company registration fields are owner-supplied — leave blank until
 * filled; the UI renders an em dash rather than inventing details.
 */

export type LegalEntity = {
  /** Registered company name, e.g. "CiteLadder Ltd". */
  legalName: string;
  /** Product / trading name shown in public copy. */
  tradingName: string;
  /** Company registration / filing number. */
  registrationNumber: string;
  /** e.g. "England and Wales" or "Delaware, U.S.A." */
  registrationJurisdiction: string;
  /** Registered office / principal business address. */
  address: string;
  /** Privacy contact email. */
  privacyEmail: string;
  /** General support / legal contact email. */
  supportEmail: string;
  /** ISO date string shown as "Last updated". */
  lastUpdated: string;
  /** Governing law label, e.g. "England and Wales". */
  governingLaw: string;
};

/**
 * Owner blockers — fill before launch. Empty strings render as "—" on pages
 * and are omitted from sentences that would otherwise invent a jurisdiction.
 */
export const LEGAL_ENTITY: LegalEntity = {
  legalName: '',
  tradingName: 'CiteLadder',
  registrationNumber: '',
  registrationJurisdiction: '',
  address: '',
  privacyEmail: '',
  supportEmail: '',
  lastUpdated: '2026-08-04',
  governingLaw: '',
};

export function legalDisplayName(): string {
  return LEGAL_ENTITY.legalName.trim() || LEGAL_ENTITY.tradingName;
}

function legalContactEmail(): string {
  return LEGAL_ENTITY.privacyEmail.trim() || LEGAL_ENTITY.supportEmail.trim();
}

type LegalSection = {
  id: string;
  title: string;
  paragraphs?: readonly string[];
  bullets?: readonly string[];
  note?: string;
};

export type LegalDocument = {
  slug: 'privacy' | 'terms' | 'cookies' | 'ai-policy';
  title: string;
  description: string;
  sections: readonly LegalSection[];
};

function paragraphSection(
  id: string,
  title: string,
  ...paragraphs: readonly string[]
): LegalSection {
  return { id, title, paragraphs };
}

function bulletSection(id: string, title: string, ...bullets: readonly string[]): LegalSection {
  return { id, title, bullets };
}

const entity = () => legalDisplayName();
const contact = () => {
  const email = legalContactEmail();
  return email || '[privacy contact — to be completed]';
};

export const PRIVACY_POLICY: LegalDocument = {
  slug: 'privacy',
  title: 'Privacy Policy',
  description:
    'How CiteLadder collects, uses, and protects personal information in connection with our website and services.',
  sections: [
    {
      id: 'who',
      title: 'Who we are',
      paragraphs: [
        `This Privacy Policy explains how ${entity()} (“CiteLadder”, “we”, “us”, or “our”) collects, uses, shares, and protects personal data in connection with our website and subscription platform (the “Services”).`,
        'CiteLadder provides an AI-visibility / answer-engine optimisation (AEO) analysis product for businesses. We sell to organisations, not consumers. We do not knowingly collect personal data from anyone under 18.',
        `Where we process personal data on behalf of a customer inside the platform (for example, workspace member details or content the customer submits), the customer is the controller and we act as a processor under the applicable customer agreement. For website visitors and account contacts we process as described below, we are the controller.`,
      ],
      note: 'Company registration, address, and privacy email are listed in the footer and Contact section once completed by the owner.',
    },
    {
      id: 'scope',
      title: 'Scope',
      paragraphs: [
        'This Policy applies to personal data processed in connection with our public websites, marketing and sales activities, demos, and authenticated use of the Services.',
        'It does not cover third-party sites, answer engines, or tools we link to or call on your behalf (for example OpenAI, Anthropic, or Google). Their practices are governed by their own policies.',
      ],
    },
    {
      id: 'collect',
      title: 'Information we collect',
      paragraphs: [
        'We collect personal data you provide, data generated when you use the Services, and limited data from service providers that help us operate.',
      ],
      bullets: [
        'Account and contact data — name, work email, company, role, and authentication identifiers when you register, join a workspace, or request a demo.',
        'Billing data — billing name, address, tax identifiers where applicable, and limited payment metadata. Full card details are handled by our payment processor; we do not store full card numbers.',
        'Usage and device data — features used, audit and run metadata, IP address, browser/device information, error logs, and performance telemetry needed to operate and secure the Services.',
        'Customer content — prompts, brand/competitor configuration, URLs, catalog data, and other material you submit. We process this to deliver the Services; answer-engine outputs and derived scores are stored as evidence for your workspace.',
        'Provider credentials (BYOK) — API keys you supply are encrypted at rest, resolved only at execution time, and are never returned in API responses or logged in clear text.',
        'Communications — messages you send us and related support correspondence.',
      ],
    },
    {
      id: 'use',
      title: 'How we use information',
      bullets: [
        'Provide, secure, maintain, and improve the Services.',
        'Authenticate users, manage workspaces, and deliver audits, scores, and evidence views.',
        'Process payments and meet accounting, tax, and legal obligations.',
        'Communicate about the Services, including transactional notices and (where permitted) product updates; you can unsubscribe from marketing emails.',
        'Detect abuse, debug failures, and protect the integrity of the platform.',
        'Generate aggregated or de-identified statistics that do not identify you or your organisation.',
      ],
      paragraphs: [
        'We do not sell personal information. We do not use customer content to train foundation models for third parties. Operational scoring inside CiteLadder is deterministic over persisted artifacts — we do not use an LLM-as-judge to produce your visibility scores.',
      ],
    },
    {
      id: 'legal-bases',
      title: 'Legal bases (EEA / UK)',
      paragraphs: [
        'Where UK/EU GDPR applies, we rely on: performance of a contract; legitimate interests in operating, securing, and improving a B2B service (balanced against your rights); consent where required (for example certain cookies or marketing); and legal obligation where applicable.',
      ],
    },
    {
      id: 'sharing',
      title: 'How we share information',
      bullets: [
        'Service providers — hosting, email, analytics (where enabled), payment processing, and similar vendors under contract.',
        'AI providers — when you run audits with BYOK, prompts are sent to the providers you configured under your keys; responses are returned to your workspace as evidence.',
        'Affiliates and corporate transactions — if we reorganise, merge, or sell assets, information may transfer subject to this Policy or equivalent protections.',
        'Legal — when required by law, legal process, or to protect rights, safety, and security.',
      ],
    },
    {
      id: 'retention',
      title: 'Retention',
      paragraphs: [
        'We retain personal data for as long as needed to provide the Services, meet legal obligations, resolve disputes, and enforce agreements. Evidence retention for paid plans follows the retention configured for your workspace or enterprise agreement. When data is no longer needed, we delete or de-identify it.',
      ],
    },
    {
      id: 'security',
      title: 'Security',
      paragraphs: [
        'We use administrative, technical, and organisational measures designed to protect personal data, including encryption of secrets at rest, workspace-scoped access controls, and same-origin API boundaries. No method of transmission or storage is perfectly secure; we cannot guarantee absolute security.',
      ],
    },
    {
      id: 'rights',
      title: 'Your choices and rights',
      paragraphs: [
        'Depending on where you live, you may have rights to access, correct, delete, restrict, or object to certain processing, and to data portability. You may also lodge a complaint with a supervisory authority.',
        `To exercise rights, contact us at ${contact()}. We may need to verify your identity before fulfilling a request.`,
      ],
    },
    {
      id: 'international',
      title: 'International transfers',
      paragraphs: [
        'We may process and store information in countries other than where you are located. Where required, we use appropriate safeguards (such as standard contractual clauses) for cross-border transfers.',
      ],
    },
    {
      id: 'cookies',
      title: 'Cookies',
      paragraphs: [
        'We use cookies and similar technologies as described in our Cookie Policy. Essential cookies are required for authentication and security; non-essential cookies are used only where permitted.',
      ],
    },
    {
      id: 'changes',
      title: 'Changes',
      paragraphs: [
        'We may update this Policy from time to time. The “Last updated” date at the top of the page will change when we do. Material changes will be highlighted on this page or notified as required by law.',
      ],
    },
    {
      id: 'contact',
      title: 'Contact',
      paragraphs: [
        `Questions about this Policy: ${contact()}.`,
        'Postal address and registered company details appear in the site footer once completed.',
      ],
    },
  ],
};

export const TERMS_OF_SERVICE: LegalDocument = {
  slug: 'terms',
  title: 'Terms of Service',
  description: 'Terms governing use of the CiteLadder website and subscription platform.',
  sections: [
    {
      id: 'agreement',
      title: 'Agreement',
      paragraphs: [
        `These Terms of Service (“Terms”) are a contract between you (the customer organisation, “Customer”, “you”) and ${entity()} (“CiteLadder”, “we”, “us”) for use of the CiteLadder website and subscription platform (the “Services”).`,
        'By creating an account, clicking to accept, or using the Services, you agree to these Terms. If you accept on behalf of an organisation, you represent that you have authority to bind that organisation. If you do not agree, do not use the Services.',
        'Enterprise customers may supersede parts of these Terms with a signed order form or master agreement. In a conflict, the signed agreement controls for that customer.',
      ],
    },
    {
      id: 'service',
      title: 'The Services',
      paragraphs: [
        'CiteLadder provides tools to measure how brands and products appear in answer-engine responses, score those appearances from persisted evidence, and related AEO analysis features described in the product.',
        'Features, limits, and pricing are set by your plan, the live billing catalog, and any enterprise agreement. We may improve or modify the Services; we will not materially reduce core paid functionality without notice where required.',
      ],
    },
    {
      id: 'accounts',
      title: 'Accounts and workspaces',
      bullets: [
        'You are responsible for account credentials, workspace membership, and activity under your accounts.',
        'You must provide accurate registration information and keep it current.',
        'You must not share login credentials or permit use outside your organisation except as allowed by your plan (for example invited seats).',
        'We may suspend access for security incidents, non-payment, or material breach.',
      ],
    },
    paragraphSection(
      'customer-data',
      'Customer data and BYOK',
      'You retain ownership of prompts, brand configuration, catalog data, and other content you submit (“Customer Data”). You grant us a limited licence to host, process, and display Customer Data solely to provide the Services.',
      'If you supply provider API keys (BYOK), you authorise us to use those keys only to execute the audits and calls you initiate. Keys are encrypted at rest and must not be shared outside your organisation. You are responsible for provider usage charges billed by those providers.',
      'You represent that you have the rights and consents needed to submit Customer Data and to run queries that may return third-party content.',
    ),
    bulletSection(
      'acceptable-use',
      'Acceptable use',
      'Do not misuse the Services, attempt unauthorised access, or interfere with platform integrity.',
      'Do not use the Services to violate law, infringe others’ rights, or probe third-party systems beyond what the product is designed to do.',
      'Do not reverse engineer the Services except where mandatory law allows.',
      'Do not resell or white-label the Services without a written agreement.',
    ),
    paragraphSection(
      'fees',
      'Fees and taxes',
      'Self-serve plans are billed as shown at checkout or in the billing catalog. Enterprise fees follow the order form. Fees are non-refundable except where required by law or expressly stated.',
      'You are responsible for applicable taxes. Provider model usage under BYOK is billed by the provider to you and is not marked up by CiteLadder.',
    ),
    paragraphSection(
      'ip',
      'Intellectual property',
      'CiteLadder and its licensors own the Services, software, documentation, and branding. These Terms do not transfer ownership of our IP to you.',
      'Feedback you provide may be used to improve the Services without obligation to you.',
    ),
    paragraphSection(
      'disclaimer',
      'Disclaimers',
      'THE SERVICES ARE PROVIDED “AS IS” AND “AS AVAILABLE”. TO THE MAXIMUM EXTENT PERMITTED BY LAW, WE DISCLAIM ALL WARRANTIES, EXPRESS OR IMPLIED, INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.',
      'Answer-engine outputs change over time. Scores and evidence reflect measurements under the conditions recorded with each run; they are not guarantees of future visibility, ranking, or commercial outcomes.',
    ),
    paragraphSection(
      'liability',
      'Limitation of liability',
      'TO THE MAXIMUM EXTENT PERMITTED BY LAW, CITELADDER WILL NOT BE LIABLE FOR INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR FOR LOST PROFITS, REVENUE, OR DATA, EVEN IF ADVISED OF THE POSSIBILITY.',
      'OUR AGGREGATE LIABILITY UNDER THESE TERMS WILL NOT EXCEED THE AMOUNTS YOU PAID TO US FOR THE SERVICES IN THE TWELVE (12) MONTHS BEFORE THE CLAIM. SOME JURISDICTIONS DO NOT ALLOW CERTAIN LIMITATIONS; IN THOSE CASES OUR LIABILITY IS LIMITED TO THE MAXIMUM PERMITTED BY LAW.',
    ),
    paragraphSection(
      'termination',
      'Term and termination',
      'These Terms continue while you use the Services. You may stop using the Services and close your account as supported in-product. We may terminate or suspend for material breach, unlawful use, or non-payment.',
      'On termination, your right to access the Services ends. Provisions that by nature should survive (including IP, disclaimers, limitations, and governing law) will survive.',
    ),
    paragraphSection(
      'law',
      'Governing law',
      LEGAL_ENTITY.governingLaw.trim()
        ? `These Terms are governed by the laws of ${LEGAL_ENTITY.governingLaw}, without regard to conflict-of-law rules. Courts in that jurisdiction will have exclusive venue, except where mandatory consumer or local law provides otherwise.`
        : 'Governing law and venue will be stated here once completed by the owner. Until then, disputes will be resolved under applicable law in a competent court of the place where CiteLadder is established.',
    ),
    paragraphSection(
      'contact',
      'Contact',
      `Questions about these Terms: ${LEGAL_ENTITY.supportEmail.trim() || contact()}.`,
    ),
  ],
};

export const COOKIE_POLICY: LegalDocument = {
  slug: 'cookies',
  title: 'Cookie Policy',
  description: 'How CiteLadder uses cookies and similar technologies on the website and platform.',
  sections: [
    {
      id: 'intro',
      title: 'Introduction',
      paragraphs: [
        `This Cookie Policy explains how ${entity()} (“CiteLadder”, “we”, “us”) uses cookies and similar technologies on our websites and Services. It should be read with our Privacy Policy.`,
        'Cookies are small text files stored on your device. We also use related technologies such as local storage and pixels where needed for security, preferences, or (where enabled) analytics.',
      ],
    },
    {
      id: 'types',
      title: 'Types of cookies we use',
      bullets: [
        'Strictly necessary — authentication session cookies, CSRF/security tokens, and load-balancing cookies required for the Services to function. These do not require consent where the law provides an exemption for essential cookies.',
        'Preferences — remember UI choices such as pricing credential-mode toggles stored in the browser.',
        'Analytics and performance — if enabled, help us understand aggregate traffic and product usage. Non-essential analytics cookies are used only with consent where required.',
        'Marketing — if enabled in future, may measure campaign effectiveness. We will update this Policy and request consent where required before enabling them.',
      ],
    },
    {
      id: 'table',
      title: 'Cookie categories (summary)',
      paragraphs: [
        'Exact cookie names may change as we ship product updates. Categories we use or may use:',
      ],
      bullets: [
        'Session / auth — keeps you signed in to the workspace (essential).',
        'Security — protects forms and API calls (essential).',
        'Preferences — stores non-sensitive UI choices (functional).',
        'Analytics — measures site or product usage when enabled (analytics; consent where required).',
      ],
      note: 'Owner: replace this summary with a concrete cookie table (name, purpose, duration, category) before launch if analytics or marketing tags are installed.',
    },
    {
      id: 'manage',
      title: 'How to manage cookies',
      paragraphs: [
        'You can control cookies through your browser settings (block, delete, or alert on cookies). Blocking essential cookies may prevent sign-in or break core features.',
        'Where a consent banner is available on the site, you can update non-essential preferences there. If no banner is shown, only essential cookies are in use, or preferences are managed via browser controls.',
      ],
    },
    {
      id: 'third-parties',
      title: 'Third parties',
      paragraphs: [
        'Some cookies may be set by processors that help us host, secure, or analyse the Services. Those parties process data under contract. Answer engines you connect via BYOK set their own cookies on their sites, not on CiteLadder.',
      ],
    },
    {
      id: 'changes',
      title: 'Changes',
      paragraphs: [
        'We may update this Cookie Policy as our practices change. The “Last updated” date will be revised when we do.',
      ],
    },
    {
      id: 'contact',
      title: 'Contact',
      paragraphs: [`Questions: ${contact()}.`],
    },
  ],
};

export const AI_POLICY: LegalDocument = {
  slug: 'ai-policy',
  title: 'AI Policy',
  description:
    'How CiteLadder uses AI systems in the product and what we do not do with your data.',
  sections: [
    {
      id: 'overview',
      title: 'Overview',
      paragraphs: [
        `${entity()} operates CiteLadder, an AEO analysis product. We observe how answer engines describe brands and products, persist raw responses as evidence, and score them with deterministic rules.`,
        'This AI Policy summarises how AI systems are involved. It does not replace the Privacy Policy or Terms of Service.',
      ],
    },
    {
      id: 'how',
      title: 'How AI is used',
      bullets: [
        'Answer engines (ChatGPT, Gemini, Claude, and any others you configure) generate responses when you run audits. Those calls use your BYOK credentials where configured.',
        'Scoring of mentions, citations, and related visibility metrics is deterministic over persisted artifacts — not an LLM judging another model’s answer.',
        'Optional product features may use models for assistance (for example drafting or research helpers). When they do, we will describe the purpose in-product.',
      ],
    },
    {
      id: 'not',
      title: 'What we do not do',
      bullets: [
        'We do not sell Customer Data.',
        'We do not use Customer Data to train third-party foundation models.',
        'We do not fabricate scores when evidence is missing — unavailable metrics render as an em dash.',
      ],
    },
    {
      id: 'human',
      title: 'Human oversight',
      paragraphs: [
        'CiteLadder is a measurement and evidence tool for professional teams. You remain responsible for decisions you make using the outputs. Raw answers and rule versions are available so you can verify scores.',
      ],
    },
    {
      id: 'contact',
      title: 'Contact',
      paragraphs: [`Questions about this Policy: ${contact()}.`],
    },
  ],
};

export const FOOTER_LEGAL_LINKS = [
  { label: 'Terms of Service', href: '/terms' },
  { label: 'Privacy Policy', href: '/privacy' },
  { label: 'Cookies', href: '/cookies' },
  { label: 'AI Policy', href: '/ai-policy' },
] as const;
