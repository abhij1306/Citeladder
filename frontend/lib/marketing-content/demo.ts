/**
 * `/demo` copy — the single edit site for the demo funnel. The funnel has
 * three states: an approved booking URL (DEMO_BOOKING_URL), a public sales
 * address (PUBLIC_SALES_EMAIL), or neither — and all three must convert,
 * because every primary CTA on the surface lands here. The env values are
 * owner-supplied (blockers B1/B2); until one exists the page converts to
 * self-serve instead of asking the visitor to come back.
 */

export const DEMO_META = {
  title: 'Book an enterprise demo',
  description:
    'See how CiteLadder connects AI visibility, site health, demand evidence, and content workflows for enterprise teams.',
} as const;

export const DEMO_HERO = {
  eyebrow: 'Enterprise demo',
  title: 'Turn AI visibility into a measurable workstream.',
  accent: 'Bring the evidence to your next review.',
  lead: 'We’ll map your answer-engine measurement goals to site health, demand, content workflows, and the evidence your team needs to inspect every result.',
} as const;

/** "What to expect" cards — grounded in the enterprise limit dials. */
export const DEMO_CARDS = [
  [
    'Measurement design',
    'Prompts, engines, repetitions, evidence, and reporting for your category.',
  ],
  ['Operating model', 'Projects, seats, retention, provider keys, and support expectations.'],
  ['Rollout plan', 'A practical path from first crawl to recurring measurement and review.'],
] as const;

/**
 * Rendered when neither a booking URL nor a sales address is configured:
 * the page converts to self-serve and says plainly when the call option
 * arrives. No contact details are collected on this page in any state.
 */
export const DEMO_SELF_SERVE_FALLBACK =
  'Self-serve signup is open now — create a workspace, connect your own provider keys, and run ' +
  'a first audit. Prefer to talk first? Enterprise volume, security review, and rollout planning ' +
  'are handled in a scheduled conversation when the booking link is available.';
