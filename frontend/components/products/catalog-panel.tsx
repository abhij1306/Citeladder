'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query';

import { integrationsApi, type IntegrationSyncRun } from '@/lib/api/integrations';
import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import { productsApi, type ProductInput } from '@/lib/api/products';
import { queryKeys } from '@/lib/api/query-keys';
import type { Product } from '@/lib/api/types';
import { isActiveSyncRun, SYNC_RUN_POLL_MS } from '@/lib/integrations/sync-runs';
import type { useCatalogQueries } from '@/lib/products/use-products-screen';

import { CatalogPanelContent } from './catalog-panel-content';

type CatalogQueries = ReturnType<typeof useCatalogQueries>;

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : 'Something went wrong. Please try again.';
}

function activeSyncConnections(health: CatalogQueries['catalogHealthQuery']['data']) {
  return (health?.connections ?? []).filter(
    (connection) =>
      connection.latest_sync !== null && isActiveSyncRun(connection.latest_sync.status),
  );
}

function syncOverrides(queries: { data?: IntegrationSyncRun }[]) {
  const overrides: Record<string, IntegrationSyncRun> = {};
  for (const query of queries) if (query.data) overrides[query.data.connection_id] = query.data;
  return overrides;
}

/** Catalog controller: mutation and polling ownership stays here; rendering is isolated in the view. */
export function CatalogPanel({
  projectId,
  queries,
}: Readonly<{ projectId: string; queries: CatalogQueries }>) {
  const queryClient = useQueryClient();
  const { productsQuery, catalogHealthQuery } = queries;
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Product | undefined>();
  const [importOpen, setImportOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Product | null>(null);
  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: queryKeys.products.list(projectId) }),
    [projectId, queryClient],
  );
  const closeForm = () => {
    setFormOpen(false);
    setEditing(undefined);
  };
  const createMutation = useMutation({
    mutationFn: (input: ProductInput) => productsApi.create(projectId, input),
    onSuccess: async () => {
      await invalidate();
      closeForm();
    },
  });
  const updateMutation = useMutation({
    mutationFn: (vars: { id: string; input: ProductInput }) =>
      productsApi.update(vars.id, vars.input),
    onSuccess: async () => {
      await invalidate();
      closeForm();
    },
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => productsApi.remove(id),
    onSuccess: async () => {
      await invalidate();
      setPendingDelete(null);
    },
  });
  const importMutation = useMutation({
    mutationFn: (rows: ProductInput[]) => productsApi.importRows(projectId, rows),
    onSuccess: invalidate,
  });
  const activeSyncs = useMemo(
    () => activeSyncConnections(catalogHealthQuery.data),
    [catalogHealthQuery.data],
  );
  const syncQueries = useQueries({
    queries: activeSyncs.map((connection) => ({
      queryKey: queryKeys.integrations.sync(
        connection.connection_id,
        connection.latest_sync!.sync_run_id,
      ),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        integrationsApi.getSync(connection.connection_id, connection.latest_sync!.sync_run_id, {
          signal,
        }),
      refetchInterval: (query: { state: { data?: IntegrationSyncRun; status: string } }) =>
        query.state.status === 'error'
          ? false
          : !query.state.data || isActiveSyncRun(query.state.data.status)
            ? SYNC_RUN_POLL_MS
            : false,
    })),
  });
  const liveSyncOverrides = useMemo(() => syncOverrides(syncQueries), [syncQueries]);
  const allTerminal =
    activeSyncs.length > 0 &&
    syncQueries.every((query) => query.data && !isActiveSyncRun(query.data.status));
  useEffect(() => {
    if (!allTerminal) return;
    void queryClient.invalidateQueries({ queryKey: queryKeys.commerce.catalogHealth(projectId) });
    void invalidate();
    void queryClient.invalidateQueries({ queryKey: queryKeys.integrations.all });
  }, [allTerminal, invalidate, projectId, queryClient]);
  const formError = createMutation.isError
    ? errorMessage(createMutation.error)
    : updateMutation.isError
      ? errorMessage(updateMutation.error)
      : undefined;
  const importError = importMutation.isError
    ? mutationNoticeForError(importMutation.error, { action: 'import the products' })
    : undefined;
  const deleteNotice = deleteMutation.isError
    ? mutationNoticeForError(deleteMutation.error, { action: 'delete the product' })
    : undefined;

  return (
    <CatalogPanelContent
      products={productsQuery.data}
      loading={productsQuery.isLoading}
      error={productsQuery.isError}
      onRetry={() => productsQuery.refetch()}
      health={catalogHealthQuery.data ?? null}
      healthPending={catalogHealthQuery.isPending}
      syncOverrides={liveSyncOverrides}
      formOpen={formOpen}
      editing={editing}
      importOpen={importOpen}
      pendingDelete={pendingDelete}
      isSaving={createMutation.isPending || updateMutation.isPending}
      formError={formError}
      importPending={importMutation.isPending}
      importError={importError}
      importResult={importMutation.data?.summary ?? null}
      deletePending={deleteMutation.isPending}
      deleteNotice={deleteNotice}
      onOpenImport={() => {
        importMutation.reset();
        setImportOpen(true);
      }}
      onOpenAdd={() => {
        setEditing(undefined);
        setFormOpen(true);
      }}
      onEdit={(product) => {
        setEditing(product);
        setFormOpen(true);
      }}
      onDelete={setPendingDelete}
      onFormOpenChange={setFormOpen}
      onFormSubmit={async (input) => {
        if (editing) await updateMutation.mutateAsync({ id: editing.id, input });
        else await createMutation.mutateAsync(input);
      }}
      onImportOpenChange={(open) => {
        if (!open) importMutation.reset();
        setImportOpen(open);
      }}
      onImportRows={async (rows) => {
        await importMutation.mutateAsync(rows);
      }}
      onImportRetry={() => {
        if (importMutation.variables) importMutation.mutate(importMutation.variables);
      }}
      onDeleteOpenChange={(open) => {
        if (!open) {
          setPendingDelete(null);
          deleteMutation.reset();
        }
      }}
      onDeleteConfirm={() => {
        if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
      }}
    />
  );
}
