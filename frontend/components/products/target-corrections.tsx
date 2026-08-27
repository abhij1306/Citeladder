'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { commerceApi } from '@/lib/api/commerce';
import { queryKeys } from '@/lib/api/query-keys';
import type {
  CommerceCatalog,
  CommerceProduct,
  CommerceProductEdit,
  CommerceTarget,
} from '@/lib/api/schemas/commerce-suite';

function productEdits(product: CommerceProduct, name: string, price: number | null) {
  const edits: CommerceProductEdit = {};
  if (name !== product.name) edits.name = name;
  if (price !== product.price) edits.price = price;
  return edits;
}

/**
 * Correct the selected target, in place.
 *
 * Corrections used to be an `Edit` / `Rename` button on every row of a wide
 * catalog table, which is a column of buttons for a thing you do rarely. The
 * target is already selected here, so the correction belongs to it.
 */
export function TargetCorrections({
  projectId,
  target,
  catalog,
}: Readonly<{
  projectId: string;
  target: CommerceTarget;
  catalog: CommerceCatalog | undefined;
}>) {
  const [open, setOpen] = useState(false);
  if (!catalog) return null;
  return (
    <details
      className="text-sm"
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="text-secondary cursor-pointer">Correct this {target.kind}</summary>
      <div className="pt-2">
        {target.kind === 'category' ? (
          <CategoryFields projectId={projectId} target={target} catalog={catalog} />
        ) : (
          <ProductFields projectId={projectId} target={target} catalog={catalog} />
        )}
      </div>
    </details>
  );
}

function CategoryFields({
  projectId,
  target,
  catalog,
}: Readonly<{ projectId: string; target: CommerceTarget; catalog: CommerceCatalog }>) {
  const client = useQueryClient();
  const category = catalog.categories.find((row) => row.id === target.id);
  const [name, setName] = useState(category?.name ?? '');
  const mutation = useMutation({
    mutationFn: () => commerceApi.editCategory(projectId, target.id, { name }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.commerce.catalog(projectId) }),
  });
  if (!category) return null;
  return (
    <div className="grid gap-2">
      <Input
        aria-label="Category name"
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      {mutation.isError ? <Alert tone="danger">The category correction failed.</Alert> : null}
      <div>
        <Button
          size="sm"
          disabled={!name.trim() || name === category.name || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          Save category
        </Button>
      </div>
    </div>
  );
}

function ProductFields({
  projectId,
  target,
  catalog,
}: Readonly<{ projectId: string; target: CommerceTarget; catalog: CommerceCatalog }>) {
  const client = useQueryClient();
  const product = catalog.products.find((row) => row.id === target.id);
  const [name, setName] = useState(product?.name ?? '');
  const [price, setPrice] = useState(product?.price?.toString() ?? '');
  const parsed = price.trim() ? Number(price) : null;
  const priceValid = parsed == null || (Number.isFinite(parsed) && parsed >= 0);
  const edits = product ? productEdits(product, name, parsed) : {};
  const mutation = useMutation({
    mutationFn: () => commerceApi.editProduct(projectId, target.id, edits),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.commerce.catalog(projectId) }),
  });
  if (!product) return null;
  return (
    <div className="grid gap-2">
      <Input
        aria-label="Product name"
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <Input
        aria-label="Product price"
        inputMode="decimal"
        value={price}
        onChange={(event) => setPrice(event.target.value)}
      />
      {mutation.isError ? <Alert tone="danger">The product correction failed.</Alert> : null}
      <div>
        <Button
          size="sm"
          disabled={!priceValid || !Object.keys(edits).length || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          Save correction
        </Button>
      </div>
    </div>
  );
}
