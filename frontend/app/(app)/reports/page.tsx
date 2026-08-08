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
    <div className="border-border-subtle bg-panel rounded-lg border p-8">
      <h1 className="text-foreground text-base font-semibold">Reports</h1>
      <p className="text-muted mt-2 max-w-[60ch] text-sm leading-relaxed">
        Snapshots and exports. Not yet available.
      </p>
    </div>
  );
}
