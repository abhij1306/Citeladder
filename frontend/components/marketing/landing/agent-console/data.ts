/**
 * The three intelligence layers prompt the Growth Agent, and the agent answers.
 * Each exchange is written from that layer's own capability list in
 * `LANDING_CONTENT.platform.modules` — nothing here claims a capability the
 * product page does not already state, and no exchange invents a metric.
 */
export const SCRIPT = [
  {
    icon: 'site' as const,
    name: 'Site Health',
    role: 'Crawls and classifies every page, then re-verifies after changes.',
    prompt: 'Recrawl complete — gap rules flagged uncovered questions on the service pages.',
    reply: 'Queuing an evidence-grounded brief for each gap. Saving a draft stays your decision.',
  },
  {
    icon: 'content' as const,
    name: 'Content Intelligence',
    role: 'Turns detected gaps into briefs, schema, and verified drafts.',
    prompt: 'Draft checked against project facts — no unsupported claims. Ready for schema.',
    reply: 'Generating FAQPage JSON-LD, then scheduling a post-publication verification pass.',
  },
  {
    icon: 'demand' as const,
    name: 'Demand Intelligence',
    role: 'Unifies Search Console, GA4, and AI visibility signals.',
    prompt: 'Search Console, GA4, and AI visibility are unified for this cluster.',
    reply: 'Reprioritizing the queue by actual impact. Every step lands in the audit log.',
  },
];

export type Phase = 'prompt' | 'thinking' | 'hold';
export type Entry = {
  id: number;
  layer: number;
  from: 'layer' | 'agent';
  text: string;
  /**
   * Set on the agent entry that was just committed from the live `reply`
   * bubble. The live bubble is suppressed against THIS flag rather than by
   * comparing the log tail to `SCRIPT[active].reply`: `push` and `setActive`
   * land in the same batch, so by the time that comparison ran `active` had
   * already advanced and it never matched — leaving the committed entry and
   * the live bubble both on screen for a frame. That double-render was the
   * flicker at the end of every exchange.
   */
  justCommitted?: boolean;
};

export const PROMPT_MS = 22;
export const THINKING_MS = 1000;
export const HOLD_MS = 2200;
/** Only the newest exchange and a half stay on screen, so the window never grows. */
export const LOG_LIMIT = 3;
