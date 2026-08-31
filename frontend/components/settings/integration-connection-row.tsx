'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BarChart3, Globe, Loader2, Search, type LucideIcon } from 'lucide-react';
import { useEffect, useState } from 'react';

import { FAMILY_META, type GrantModel } from '@/components/settings/grant-model';
import { PropertyPicker, useActiveMapping } from '@/components/settings/property-picker';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import {
  integrationsApi,
  type IntegrationConnection,
  type IntegrationProvider,
} from '@/lib/api/integrations';
import { queryKeys } from '@/lib/api/query-keys';
import { formatShortDate, formatUtcTimestamp } from '@/lib/format';
import { isActiveSyncRun, SYNC_RUN_BADGE, SYNC_RUN_POLL_MS } from '@/lib/integrations/sync-runs';

type ConnectionMutation = {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  mutate: () => void;
};
type SyncRun = Awaited<ReturnType<typeof integrationsApi.getSync>>;

const PROVIDER_META: Record<IntegrationProvider, { label: string; Icon: LucideIcon }> = {
  gsc: { label: 'Google Search Console', Icon: Search },
  ga4: { label: 'Google Analytics 4', Icon: BarChart3 },
  bing: { label: 'Bing Webmaster Tools', Icon: Globe },
};

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : 'Something went wrong. Please try again.';
}

function ConnectionActions({
  connection,
  grant,
  label,
  Icon,
  busy,
  hasProperty,
  runActive,
  testPending,
  syncPending,
  onTest,
  onSync,
  onDisconnect,
}: Readonly<{
  connection: IntegrationConnection;
  grant: GrantModel;
  label: string;
  Icon: LucideIcon;
  busy: boolean;
  hasProperty: boolean;
  runActive: boolean;
  testPending: boolean;
  syncPending: boolean;
  onTest: () => void;
  onSync: () => void;
  onDisconnect: () => void;
}>) {
  const syncDisabled = busy || runActive || !hasProperty || grant.status !== 'connected';

  return (
    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <span
          aria-hidden
          className="bg-well border-border-subtle text-secondary mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md border"
        >
          <Icon className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-foreground truncate text-sm font-medium">{label}</div>
          <PropertyPicker connection={connection} disabled={busy} />
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5 self-end sm:self-auto">
        <Button
          variant="secondary"
          size="sm"
          className="min-w-[56px]"
          onClick={onTest}
          disabled={busy}
        >
          {testPending ? 'Testing…' : 'Test'}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          className="min-w-[86px]"
          onClick={onSync}
          title={hasProperty ? undefined : 'Select a property first'}
          disabled={syncDisabled}
        >
          {syncPending ? (
            <>
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
              Syncing…
            </>
          ) : (
            'Sync now'
          )}
        </Button>
        <Button variant="destructiveGhost" size="sm" onClick={onDisconnect} disabled={busy}>
          Disconnect
        </Button>
      </div>
    </div>
  );
}

function ConnectionMetadata({
  connection,
  activeRun,
  runActive,
}: Readonly<{
  connection: IntegrationConnection;
  activeRun: SyncRun | null;
  runActive: boolean;
}>) {
  return (
    <div className="border-border-subtle/70 mt-3 flex flex-wrap items-center justify-between gap-2 border-t pt-2.5">
      <div className="flex items-center gap-2">
        <span className={eyebrowClasses}>Last synced</span>
        <span className="text-secondary font-mono text-xs tabular-nums">
          {connection.last_synced_at ? formatUtcTimestamp(connection.last_synced_at) : 'Never'}
        </span>
      </div>
      {runActive && activeRun ? (
        <div className="flex items-center gap-2">
          <Badge variant="run-status" value={SYNC_RUN_BADGE[activeRun.status]}>
            {activeRun.status.replace('_', ' ')}
          </Badge>
          <span className="text-muted font-mono text-xs whitespace-nowrap">
            {activeRun.status === 'running'
              ? `${activeRun.row_count.toLocaleString('en-US')} rows · window ${formatShortDate(activeRun.window_start)}–${formatShortDate(activeRun.window_end)}`
              : `Enqueued ${formatUtcTimestamp(activeRun.created_at)} · waiting for a worker`}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function DisconnectDialog({
  connection,
  grant,
  label,
  open,
  setOpen,
  deleteMutation,
}: Readonly<{
  connection: IntegrationConnection;
  grant: GrantModel;
  label: string;
  open: boolean;
  setOpen: (open: boolean) => void;
  deleteMutation: ConnectionMutation;
}>) {
  const lastConnection = grant.connections.length === 1;
  const siblings = grant.connections.filter((sibling) => sibling.id !== connection.id);
  const familyTitle = FAMILY_META[grant.family].title;

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!deleteMutation.isPending) setOpen(nextOpen);
      }}
      title={`Disconnect ${label}`}
      description={
        <>
          Remove <span className="font-mono text-xs">{connection.account_ref}</span> from this
          workspace?
        </>
      }
      footer={
        <>
          <Button
            variant="secondary"
            onClick={() => setOpen(false)}
            disabled={deleteMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => deleteMutation.mutate()}
            disabled={deleteMutation.isPending}
          >
            {deleteMutation.isPending
              ? 'Disconnecting…'
              : lastConnection
                ? 'Disconnect & revoke'
                : 'Disconnect'}
          </Button>
        </>
      }
    >
      <div className="grid gap-2">
        {lastConnection ? (
          <>
            <p className="text-secondary text-sm">
              This is the <strong className="text-foreground font-medium">last connection</strong>{' '}
              on the {familyTitle} OAuth grant, so disconnecting it also{' '}
              <strong className="text-foreground font-medium">revokes the grant</strong>:
              CiteLadder&rsquo;s access at {familyTitle} is removed and the stored tokens are
              deleted. Previously imported {label} data is kept.
            </p>
            <p className="text-secondary text-sm">
              If {familyTitle}&nbsp;can&rsquo;t be reached to complete the revocation, the grant
              moves to <strong className="text-foreground font-medium">pending revocation</strong>{' '}
              and CiteLadder retries in the background.
            </p>
          </>
        ) : (
          <>
            <p className="text-secondary text-sm">
              CiteLadder stops syncing {label} for{' '}
              <span className="font-mono text-xs">{connection.account_ref}</span> and removes this
              connection. Previously imported data is kept.
            </p>
            <p className="text-secondary text-sm">
              <strong className="text-foreground font-medium">
                {siblings.map((sibling) => PROVIDER_META[sibling.provider].label).join(' and ')}{' '}
                stays connected
              </strong>
              , so the shared {familyTitle} OAuth grant remains active. The grant is only revoked —
              and {familyTitle} access removed for every connection — when its last connection is
              disconnected.
            </p>
          </>
        )}
        {deleteMutation.isError ? (
          <Alert tone="danger">{errorMessage(deleteMutation.error)}</Alert>
        ) : null}
      </div>
    </Dialog>
  );
}

function ConnectionRowView({
  connection,
  grant,
  testMutation,
  syncMutation,
  deleteMutation,
  testState,
  confirmOpen,
  setConfirmOpen,
  activeRun,
  runActive,
  busy,
  hasProperty,
}: Readonly<{
  connection: IntegrationConnection;
  grant: GrantModel;
  testMutation: ConnectionMutation;
  syncMutation: ConnectionMutation;
  deleteMutation: ConnectionMutation;
  testState: { ok: boolean; message: string } | null;
  confirmOpen: boolean;
  setConfirmOpen: (open: boolean) => void;
  activeRun: SyncRun | null;
  runActive: boolean;
  busy: boolean;
  hasProperty: boolean;
}>) {
  const { label, Icon } = PROVIDER_META[connection.provider];

  return (
    <div
      className="bg-panel border-border-subtle rounded-md border p-3.5 shadow-2xs"
      data-testid={`connection-row-${connection.provider}`}
    >
      <ConnectionActions
        connection={connection}
        grant={grant}
        label={label}
        Icon={Icon}
        busy={busy}
        hasProperty={hasProperty}
        runActive={runActive}
        testPending={testMutation.isPending}
        syncPending={syncMutation.isPending}
        onTest={testMutation.mutate}
        onSync={syncMutation.mutate}
        onDisconnect={() => setConfirmOpen(true)}
      />
      <ConnectionMetadata connection={connection} activeRun={activeRun} runActive={runActive} />
      {testState ? (
        <div className="pt-2.5">
          <Alert tone={testState.ok ? 'success' : 'danger'}>{testState.message}</Alert>
        </div>
      ) : null}
      {syncMutation.isError ? (
        <div className="pt-2.5">
          <Alert tone="danger">{errorMessage(syncMutation.error)}</Alert>
        </div>
      ) : null}
      <DisconnectDialog
        connection={connection}
        grant={grant}
        label={label}
        open={confirmOpen}
        setOpen={setConfirmOpen}
        deleteMutation={deleteMutation}
      />
    </div>
  );
}

/** Polling and mutation owner for one connection on an OAuth grant. */
export function ConnectionRow({
  connection,
  grant,
}: Readonly<{ connection: IntegrationConnection; grant: GrantModel }>) {
  const queryClient = useQueryClient();
  const [testState, setTestState] = useState<{ ok: boolean; message: string } | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [activeSyncId, setActiveSyncId] = useState<string | null>(null);
  const testMutation = useMutation({
    mutationFn: () => integrationsApi.test(connection.id),
    onSuccess: (result) => {
      setTestState(
        result.status === 'ok'
          ? { ok: true, message: 'Connection succeeded.' }
          : {
              ok: false,
              message: result.detail
                ? `Connection failed (${result.error_code || 'unknown'}): ${result.detail}`
                : `Connection failed (${result.error_code || 'unknown'}).`,
            },
      );
    },
    onError: (error) => setTestState({ ok: false, message: errorMessage(error) }),
  });
  // The terminal sync poll invalidates integrations; enqueueing alone persists no projection.
  // react-doctor-disable-next-line
  const syncMutation = useMutation({
    mutationFn: () => integrationsApi.sync(connection.id),
    onSuccess: (enqueued) => {
      setTestState(null);
      setActiveSyncId(enqueued.sync_run_id);
    },
  });
  const syncRunQuery = useQuery({
    queryKey: queryKeys.integrations.sync(connection.id, activeSyncId ?? ''),
    queryFn: ({ signal }) => integrationsApi.getSync(connection.id, activeSyncId ?? '', { signal }),
    enabled: activeSyncId !== null,
    refetchInterval: (query) => {
      const run = query.state.data;
      return !run || isActiveSyncRun(run.status) ? SYNC_RUN_POLL_MS : false;
    },
  });
  const activeRun = syncRunQuery.data ?? null;
  const runActive = activeRun !== null && isActiveSyncRun(activeRun.status);
  const runTerminal = activeRun !== null && !isActiveSyncRun(activeRun.status);

  useEffect(() => {
    if (runTerminal) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.integrations.all });
    }
  }, [queryClient, runTerminal]);

  const deleteMutation = useMutation({
    mutationFn: () => integrationsApi.delete(connection.id),
    onSuccess: async () => {
      setConfirmOpen(false);
      await queryClient.invalidateQueries({ queryKey: queryKeys.integrations.all });
    },
  });
  const busy = testMutation.isPending || syncMutation.isPending || deleteMutation.isPending;
  const hasProperty = useActiveMapping(connection.id) !== null;

  return (
    <ConnectionRowView
      connection={connection}
      grant={grant}
      testMutation={testMutation}
      syncMutation={syncMutation}
      deleteMutation={deleteMutation}
      testState={testState}
      confirmOpen={confirmOpen}
      setConfirmOpen={setConfirmOpen}
      activeRun={activeRun}
      runActive={runActive}
      busy={busy}
      hasProperty={hasProperty}
    />
  );
}
