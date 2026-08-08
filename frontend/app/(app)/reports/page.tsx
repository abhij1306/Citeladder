/**
 * Reports (§4) — snapshots and exports.
 *
 * Declared in the sidebar as one of the six destinations so the architecture
 * is legible; the surface itself lands with stage 6 (§10 step 9). Renders as
 * declared-but-empty rather than 404ing, because a sidebar entry that resolves
 * to nothing violates the live-navigation rule.
 */
export default function ReportsPage() {
  return (
    <div className="bg-panel shadow-card rounded-lg p-8">
      {/* No heading here: the shell's sr-only <h1> already names the route and
          the sidebar shows it, so a visible "Reports" would say it a third time. */}
      <p className="text-foreground text-sm font-medium">Not yet available</p>
      <p className="text-muted mt-2 max-w-[60ch] text-sm leading-relaxed">Snapshots and exports.</p>
    </div>
  );
}
