'use client';

import { useCallback, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import { productsApi, type ProductInput } from '@/lib/api/products';
import { queryKeys } from '@/lib/api/query-keys';
import type { Product } from '@/lib/api/types';
import type { useCatalogQueries } from '@/lib/products/use-products-screen';

import { CatalogPanelContent } from './catalog-panel-content';

type CatalogQueries = ReturnType<typeof useCatalogQueries>;

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : 'Something went wrong. Please try again.';
}

/** Catalog controller: mutation and polling ownership stays here; rendering is isolated in the view. */
export function CatalogPanel({
  projectId,
  queries,
}: Readonly<{ projectId: string; queries: CatalogQueries }>) {
  const queryClient = useQueryClient();
  const { productsQuery } = queries;
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
