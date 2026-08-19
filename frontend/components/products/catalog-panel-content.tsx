import { Package, Plus, Upload } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardEyebrow } from '@/components/ui/card';
import { IconChip } from '@/components/ui/icon-chip';
import { Skeleton } from '@/components/ui/skeleton';
import { displayHeadingLgClasses } from '@/components/ui/typography';
import type { IntegrationSyncRun } from '@/lib/api/integrations';
import type { MutationNotice } from '@/lib/api/mutation-notice';
import type { ProductInput } from '@/lib/api/products';
import type { CommerceCatalogHealth, Product, ProductImportSummary } from '@/lib/api/types';

import { CatalogTable } from './catalog-table';
import { ProductDeleteDialog } from './product-delete-dialog';
import { ProductFormDialog } from './product-form-dialog';
import { ProductImportDialog } from './product-import-dialog';

function CatalogEmptyState({
  onImport,
  onAdd,
}: Readonly<{ onImport: () => void; onAdd: () => void }>) {
  return (
    <Card>
      <CardContent className="grid justify-items-center gap-4 py-12 text-center">
        <CardEyebrow>Catalog</CardEyebrow>
        <IconChip>
          <Package className="size-6" aria-hidden />
        </IconChip>
        <div className="grid gap-1">
          <h2 className={displayHeadingLgClasses}>No products yet</h2>
          <p className="text-secondary max-w-md text-sm">
            Add the products you sell — manually or via CSV — so audits can measure how AI answer
            engines rank and price them against competitor products.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="md" onClick={onImport}>
            Import CSV
          </Button>
          <Button variant="primary" size="md" onClick={onAdd}>
            Add your first product
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function CatalogPanelContent({
  products,
  loading,
  error,
  onRetry,
  health,
  healthPending,
  syncOverrides,
  formOpen,
  editing,
  importOpen,
  pendingDelete,
  isSaving,
  formError,
  importPending,
  importError,
  importResult,
  deletePending,
  deleteNotice,
  onOpenImport,
  onOpenAdd,
  onEdit,
  onDelete,
  onFormOpenChange,
  onFormSubmit,
  onImportOpenChange,
  onImportRows,
  onImportRetry,
  onDeleteOpenChange,
  onDeleteConfirm,
}: Readonly<{
  products: Product[] | undefined;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  health: CommerceCatalogHealth | null;
  healthPending: boolean;
  syncOverrides: Readonly<Record<string, IntegrationSyncRun>>;
  formOpen: boolean;
  editing: Product | undefined;
  importOpen: boolean;
  pendingDelete: Product | null;
  isSaving: boolean;
  formError?: string;
  importPending: boolean;
  importError?: MutationNotice;
  importResult: ProductImportSummary | null;
  deletePending: boolean;
  deleteNotice?: MutationNotice;
  onOpenImport: () => void;
  onOpenAdd: () => void;
  onEdit: (product: Product) => void;
  onDelete: (product: Product) => void;
  onFormOpenChange: (open: boolean) => void;
  onFormSubmit: (input: ProductInput) => Promise<void>;
  onImportOpenChange: (open: boolean) => void;
  onImportRows: (rows: ProductInput[]) => Promise<void>;
  onImportRetry: () => void;
  onDeleteOpenChange: (open: boolean) => void;
  onDeleteConfirm: () => void;
}>) {
  if (loading)
    return (
      <Card aria-hidden>
        <CardContent className="grid gap-3">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-48 w-full" />
        </CardContent>
      </Card>
    );
  if (error)
    return (
      <Alert tone="danger">
        Could not load the product catalog.{' '}
        <button type="button" className="underline" onClick={onRetry}>
          Retry
        </button>
      </Alert>
    );
  const catalog = products ?? [];
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-secondary text-sm">
          {catalog.length} product{catalog.length === 1 ? '' : 's'} in the catalog
        </p>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={onOpenImport}>
            <Upload className="size-4" aria-hidden />
            Import CSV
          </Button>
          <Button variant="primary" size="sm" onClick={onOpenAdd}>
            <Plus className="size-4" aria-hidden />
            Add product
          </Button>
        </div>
      </div>
      {catalog.length ? (
        <CatalogTable
          products={catalog}
          health={health}
          healthPending={healthPending}
          syncOverrides={syncOverrides}
          onEdit={onEdit}
          onDelete={onDelete}
        />
      ) : (
        <CatalogEmptyState onImport={onOpenImport} onAdd={onOpenAdd} />
      )}
      <ProductFormDialog
        open={formOpen}
        onOpenChange={onFormOpenChange}
        product={editing}
        isSaving={isSaving}
        error={formError}
        onSubmit={onFormSubmit}
      />
      <ProductImportDialog
        open={importOpen}
        onOpenChange={onImportOpenChange}
        isImporting={importPending}
        error={importError}
        onRetry={onImportRetry}
        result={importResult}
        onImport={onImportRows}
      />
      <ProductDeleteDialog
        product={pendingDelete}
        open={pendingDelete !== null}
        onOpenChange={onDeleteOpenChange}
        isDeleting={deletePending}
        notice={deleteNotice}
        onConfirm={onDeleteConfirm}
      />
    </div>
  );
}
