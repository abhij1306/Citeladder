/**
 * Pricing PRESENTATION metadata.
 *
 * Plan limits, availability, add-ons, and enforceable checkout values come
 * from `GET /billing/catalog`. This module owns only the copy the backend has
 * no opinion about: a blurb per tier and which card is visually emphasised.
 *
 * A component that cannot reach the catalog renders a loading or error shell.
 */

/** Where the contact-only tier sends people when the catalog gives no URL. */
export { DEMO_HREF as ENTERPRISE_FALLBACK_HREF } from './nav';

/** The backend's plan keys, as the presentation layer refers to them. */
export type PlanKey = 'tier_1' | 'tier_2' | 'tier_3' | 'enterprise';

export type PlanPresentation = {
  blurb: string;
  highlighted?: boolean;
};

/**
 * Copy keyed by the exact backend plan key. A key the backend stops sending
 * simply stops rendering; a key with no entry here falls back to the catalog's
 * own description.
 */
export const PLAN_PRESENTATION: Readonly<Record<PlanKey, PlanPresentation>> = {
  tier_1: {
    blurb: 'Crawl, classify, and improve your owned pages.',
  },
  tier_2: {
    blurb: 'Site, Content, and Demand Intelligence in one workspace.',
    highlighted: true,
  },
  tier_3: { blurb: 'Higher limits for growing sites and teams.' },
  enterprise: {
    blurb: 'Custom scale, security, and evidence-workflow support.',
  },
};

/** The label on the credential-mode switch. */
export const BYOK_SWITCH_LABEL = 'Use your own API keys';

/**
 * The full BYOK disclosure, shown beside the switch.
 *
 * Both halves matter: customers pay their providers directly, AND their own
 * rate limits govern how fast a report can be produced. Promising report-ready
 * latency on someone else's quota would be a promise we cannot keep.
 */
export const BYOK_DISCLOSURE =
  'Provider usage is billed directly to your accounts with no CiteLadder markup. ' +
  'Run speed depends on your providers’ rate limits.';

/** Fallback for a malformed or stale catalog response without a plan price. */
export const FUNDED_UNAVAILABLE_LABEL = 'Not yet priced';

/** Shown for a contact-only tier. */
export const CONTACT_LABEL = 'Contact us';

/** Human labels for the capability keys the comparison grid renders. */
export const CAPABILITY_LABELS: Readonly<Record<string, string>> = {
  project_slots: 'Projects',
  prompt_slots: 'Prompts',
  monitored_urls: 'Monitored URLs',
  manual_runs_per_day: 'Manual runs per day',
  audit_credits: 'Audit credits',
  audit_cadence: 'Audit frequency',
  audit_web_search: 'Web-search-grounded audits',
  authenticated_exports: 'Authenticated exports',
};

/**
 * `prompt_slots` → `Prompt slots` when no explicit label is registered.
 *
 * The lookup is an OWN-property check: the keys come from the billing API, and
 * a plain-object map answers `__proto__`/`toString` from the prototype chain
 * with a non-string, which React cannot render as a child.
 */
export function capabilityLabel(key: string): string {
  if (Object.hasOwn(CAPABILITY_LABELS, key)) return CAPABILITY_LABELS[key];
  const words = key.replaceAll('_', ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}
