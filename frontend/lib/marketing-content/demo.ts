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
    'Discuss CiteLadder Enterprise volumes, deployment, security review, and support with the team.',
} as const;

export const DEMO_HERO = {
  eyebrow: 'Enterprise demo',
  title: 'Bring your category.',
  accent: 'Leave with a concrete rollout path.',
  lead: 'We’ll cover your answer-engine measurement goals, workspace volume, deployment constraints, security review, and the evidence your team needs to trust the output.',
} as const;

/** "What to expect" cards — grounded in the enterprise limit dials. */
export const DEMO_CARDS = [
  ['Your measurement plan', 'Prompts, engines, repetitions, evidence, and reporting.'],
  ['Your operating model', 'Seats, projects, cadence, retention, and support expectations.'],
  ['Your rollout path', 'Projects, seats, retention, and the security review your team runs.'],
] as const;

/**
 * Rendered when neither a booking URL nor a sales address is configured:
 * the page converts to self-serve and says plainly when the call option
 * arrives. No contact details are collected on this page in any state.
 */
export const DEMO_SELF_SERVE_FALLBACK =
  'Self-serve signup is open now — create a workspace, connect your own provider keys and run ' +
  'a first audit today. Prefer to talk first? Enterprise volumes, security review and rollout ' +
  'are handled by a scheduled call; the booking link is published here as soon as it is live.';
