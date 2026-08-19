import { Badge } from '@/components/ui/badge';
import type { IntegrationSyncRun } from '@/lib/api/integrations';
import type { CommerceConnectionSummary, Product } from '@/lib/api/types';
import { formatUtcTimestamp } from '@/lib/format';
import { SYNC_RUN_BADGE, syncRunStatusLabel } from '@/lib/integrations/sync-runs';

type SyncDetails = {
  status: IntegrationSyncRun['status'];
  errorCode: string | null;
  completedAt: string | null;
};

function syncDetails(
  connection: CommerceConnectionSummary,
  override: IntegrationSyncRun | undefined,
): SyncDetails | null {
  const persisted = connection.latest_sync;
  if (!persisted) return null;
  if (override?.id === persisted.sync_run_id) {
    return {
      status: override.status,
      errorCode: override.error_code,
      completedAt: override.completed_at,
    };
  }
  return {
    status: persisted.status,
    errorCode: persisted.error_code,
    completedAt: persisted.completed_at,
  };
}

function SyncStatus({ details }: Readonly<{ details: SyncDetails }>) {
  return (
    <span className="flex items-center gap-2">
      <Badge variant="run-status" value={SYNC_RUN_BADGE[details.status]}>
        {syncRunStatusLabel(details.status)}
      </Badge>
      {details.status === 'failed' && details.errorCode ? (
        <span className="text-danger-text text-2xs font-mono">{details.errorCode}</span>
      ) : null}
    </span>
  );
}

/** Bound connection sync state, preferring the freshest poll over the projection. */
export function SyncCell({
  product,
  connection,
  override,
  pending,
}: Readonly<{
  product: Product;
  connection: CommerceConnectionSummary | undefined;
  override: IntegrationSyncRun | undefined;
  pending: boolean;
}>) {
  if (pending) return <span className="text-subtle text-xs">…</span>;
  if (!product.connection_id || !connection) return <span className="text-subtle">—</span>;

  const details = syncDetails(connection, override);
  if (!details) return <span className="text-muted text-xs">Never synced</span>;

  const timestamp = details.completedAt ?? connection.last_synced_at;
  return (
    <div className="grid gap-0.5">
      <SyncStatus details={details} />
      {timestamp ? (
        <span className="text-muted text-2xs font-mono tabular-nums">
          {formatUtcTimestamp(timestamp)}
        </span>
      ) : null}
    </div>
  );
}
