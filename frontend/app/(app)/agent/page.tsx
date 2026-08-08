/**
 * Growth Agent (§7.5) — the layer route.
 *
 * No agent backend exists yet (there is no task catalog, plan/progress, or
 * roadmap projection in `lib/api`), so this declares the layer and names the
 * surfaces it will own rather than faking any of them. Listing them is the
 * point: §4 says the sidebar is the architecture, and a user should be able to
 * name the four layers after a week.
 *
 * When stage 5 lands, each item below becomes a tab here, and the
 * ContextManifest / Insight components in `components/intelligence` are the
 * contracts to build against — they already exist.
 */
const SURFACES = [
  {
    title: 'Task composer',
    detail: 'Only the task families in the backend catalog — never an open-ended prompt box.',
  },
  {
    title: 'Plan and progress',
    detail:
      'Polling is authoritative and streaming is presentation only. Waiting on you and waiting on a task render differently.',
  },
  {
    title: 'Context manifest',
    detail:
      'Included sources, omitted counts, truncation, and contradictions carried in — what makes selective context inspectable.',
  },
  {
    title: 'Results',
    detail: 'Conclusion, evidence used, artifacts created, decisions still needed, and next step.',
  },
  {
    title: 'Roadmap',
    detail:
      'The deterministic order with agent-authored grouping. A priority override renders beside it as a reversible suggestion, never as a silently reordered list.',
  },
] as const;

export default function AgentPage() {
  return (
    <div className="flex flex-col gap-6">
      {/* No heading here: the shell's sr-only <h1> already names the route and
          the sidebar shows it, so a visible "Growth Agent" would repeat it. */}
      <div className="bg-panel shadow-card rounded-lg p-8">
        <p className="text-foreground text-sm font-medium">Not yet available</p>
        <p className="text-muted mt-2 max-w-[65ch] text-sm leading-relaxed">
          The agent orchestrates the other three layers; these are the surfaces it will own.
        </p>
      </div>

      <ul className="grid gap-3 md:grid-cols-2">
        {SURFACES.map((surface) => (
          <li key={surface.title} className="bg-panel shadow-card rounded-lg p-4">
            <p className="text-foreground text-sm font-medium">{surface.title}</p>
            <p className="text-muted mt-1 text-sm leading-relaxed">{surface.detail}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
