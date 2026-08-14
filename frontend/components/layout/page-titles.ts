/**
 * Route → page title map, and the resolver the shell's top bar uses.
 *
 * Exact patterns first; everything else is a longest-prefix match. Titles live
 * here (not on the pages themselves) so there is a single title surface for the
 * whole authed area — the sibling of `nav-items.ts`, and, like it, a data module
 * rather than a component so editing `page-header.tsx` can still Fast Refresh.
 *
 * Copy is sentence case and plain language: product nouns keep their
 * capitalisation, everything else reads like a sentence.
 */
const PAGE_TITLES: ReadonlyArray<readonly [prefix: string, title: string]> = [
  ['/visibility', 'Overview'],
  ['/ai-referrals', 'AI Referrals'],
  ['/traffic', 'Traffic'],
  ['/prompts', 'Prompts'],
  ['/prompt-research', 'Prompt research'],
  ['/opportunities', 'Opportunities'],
  ['/products', 'Products'],
  ['/runs', 'Runs'],
  ['/content', 'Content'],
  ['/projects', 'Overview'],
  // §9.3: the route persists, the label is "Facts" — never "brand memory",
  // "brand knowledge", or "knowledge base".
  ['/knowledge-base', 'Facts'],
  // The four layer routes. `/site-health` MUST precede `/site`: these are
  // prefix matches, so the shorter one would otherwise swallow it.
  ['/site-health', 'Site health'],
  ['/site', 'Site'],
  ['/demand', 'Search Demand'],
  ['/agent', 'Growth Agent'],
  ['/issues', 'Issues'],
  ['/settings', 'Settings'],
  ['/providers', 'Settings'],
];

/** Deeper-route overrides (checked before the prefix table). */
const EXACT_OVERRIDES: ReadonlyArray<readonly [pattern: RegExp, title: string]> = [
  [/^\/products\/[^/]+$/, 'Product evidence'],
  [/^\/site-health\/crawls\/[^/]+\/pages\/[^/]+$/, 'Page detail'],
  [/^\/runs\/[^/]+\/executions\/[^/]+$/, 'Execution evidence'],
  [/^\/runs\/[^/]+$/, 'Run detail'],
];

export function resolveTitle(pathname: string): string {
  for (const [pattern, title] of EXACT_OVERRIDES) {
    if (pattern.test(pathname)) return title;
  }
  for (const [prefix, title] of PAGE_TITLES) {
    if (pathname === prefix || pathname.startsWith(`${prefix}/`)) return title;
  }
  return 'CiteLadder';
}
