'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { commerceApi } from '@/lib/api/commerce';
import { queryKeys } from '@/lib/api/query-keys';
import { siteHealthApi, siteHealthQueries } from '@/lib/api/site-health';
import type {
  CommerceCatalog,
  CommerceCategory,
  CommerceProduct,
} from '@/lib/api/schemas/commerce-suite';
import { ACTIVE_RUN_POLL_MS } from '@/lib/config/operational';
import type { useCommerceQueries } from '@/lib/products/use-products-screen';
import type { SiteCrawl } from '@/lib/api/types';

type CatalogQuery = ReturnType<typeof useCommerceQueries>['catalog'];

function projectionSummary(tasks: Record<string, number>) {
  const entries = Object.entries(tasks).filter(([, count]) => count > 0);
  return entries.length
    ? entries.map(([status, count]) => `${count} ${status}`).join(' · ')
    : 'No projection tasks yet';
}

function CatalogHeader({
  crawl,
  tasks,
  discoverPending,
  dashboardPending,
  siteHealthError,
  importPending,
  importError,
  result,
  onSiteHealthAction,
  onImport,
}: {
  crawl: SiteCrawl | null | undefined;
  tasks: Record<string, number>;
  discoverPending: boolean;
  dashboardPending: boolean;
  siteHealthError: boolean;
  importPending: boolean;
  importError: boolean;
  result: string;
  onSiteHealthAction: () => void;
  onImport: (file: File) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Canonical product catalog</CardTitle>
        <CardDescription>
          Site Health observations project automatically. CSV and explicit edits retain field-level
          authority.
        </CardDescription>
        <div className="flex flex-wrap gap-2">
          <Button disabled={discoverPending || dashboardPending} onClick={onSiteHealthAction}>
            {crawl ? 'Refresh from Site Health' : 'Discover from Site Health'}
          </Button>
          <a className="text-link self-center text-sm" href="/site">
            Open Site Health
          </a>
        </div>
        {crawl ? (
          <p className="text-secondary text-sm">
            Site Health crawl: {crawl.analyzed_count} /{' '}
            {crawl.total_url_count ?? crawl.visible_url_count} analyzed · {crawl.status}
          </p>
        ) : (
          <p className="text-secondary text-sm">No Site Health crawl is available yet.</p>
        )}
        <p className="text-secondary text-sm">Commerce projection: {projectionSummary(tasks)}</p>
        <Input
          aria-label="Import catalog CSV"
          type="file"
          accept=".csv,text/csv"
          disabled={importPending}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onImport(file);
          }}
        />
        {result ? <p className="text-secondary text-sm">{result}</p> : null}
        {importError ? <Alert tone="danger">The catalog import failed.</Alert> : null}
        {siteHealthError ? (
          <Alert tone="danger">Site Health progress could not be refreshed.</Alert>
        ) : null}
      </CardHeader>
    </Card>
  );
}

function categoryNames(product: CommerceProduct, catalog: CommerceCatalog) {
  const names = catalog.categories
    .filter((category) => product.category_ids.includes(category.id))
    .map((category) => category.name);
  return names.length ? names.join(', ') : 'Uncategorized';
}

function CategoryEditor({
  projectId,
  category,
  onDone,
}: {
  projectId: string;
  category: CommerceCategory;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const [name, setName] = useState(category.name);
  const [role, setRole] = useState(category.role);
  const mutation = useMutation({
    mutationFn: () => commerceApi.editCategory(projectId, category.id, { name, role }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: queryKeys.commerce.catalog(projectId) });
      onDone();
    },
  });
  return (
    <div className="grid gap-2 py-2">
      <Input
        aria-label="Category name"
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <select
        aria-label="Category role"
        className="bg-input h-8 rounded-sm border px-2 text-sm"
        value={role}
        onChange={(event) => setRole(event.target.value as CommerceCategory['role'])}
      >
        <option value="hub">Hub</option>
        <option value="leaf">Leaf</option>
        <option value="unknown">Unknown</option>
      </select>
      {mutation.isError ? <Alert tone="danger">The category correction failed.</Alert> : null}
      <div className="flex gap-2">
        <Button disabled={!name.trim() || mutation.isPending} onClick={() => mutation.mutate()}>
          Save category
        </Button>
        <Button variant="secondary" disabled={mutation.isPending} onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function ProductEditor({
  projectId,
  product,
  catalog,
  onDone,
}: {
  projectId: string;
  product: CommerceProduct;
  catalog: CommerceCatalog;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const [name, setName] = useState(product.name);
  const [brand, setBrand] = useState(product.brand);
  const [price, setPrice] = useState(product.price?.toString() ?? '');
  const [categoryIds, setCategoryIds] = useState(product.category_ids);
  const parsedPrice = price.trim() ? Number(price) : null;
  const priceValid = parsedPrice == null || (Number.isFinite(parsedPrice) && parsedPrice >= 0);
  const mutation = useMutation({
    mutationFn: () =>
      commerceApi.editProduct(projectId, product.id, {
        name,
        brand,
        price: parsedPrice,
        category_ids: categoryIds,
      }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: queryKeys.commerce.catalog(projectId) });
      onDone();
    },
  });
  const toggleCategory = (id: string) =>
    setCategoryIds((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
  return (
    <div className="grid gap-3 py-3">
      <Input
        aria-label="Product name"
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <Input
        aria-label="Product brand"
        value={brand}
        onChange={(event) => setBrand(event.target.value)}
      />
      <Input
        aria-label="Product price"
        inputMode="decimal"
        value={price}
        onChange={(event) => setPrice(event.target.value)}
      />
      <fieldset className="grid gap-2">
        <legend className="text-sm font-medium">Categories</legend>
        {catalog.categories.map((category) => (
          <label className="flex items-center gap-2 text-sm" key={category.id}>
            <input
              type="checkbox"
              checked={categoryIds.includes(category.id)}
              onChange={() => toggleCategory(category.id)}
            />
            {category.name}
          </label>
        ))}
      </fieldset>
      {mutation.isError ? <Alert tone="danger">The product correction failed.</Alert> : null}
      <div className="flex gap-2">
        <Button disabled={!priceValid || mutation.isPending} onClick={() => mutation.mutate()}>
          Save correction
        </Button>
        <Button variant="secondary" disabled={mutation.isPending} onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

export function CatalogPanel({ projectId, query }: { projectId: string; query: CatalogQuery }) {
  const client = useQueryClient();
  const [result, setResult] = useState('');
  const [editingId, setEditingId] = useState('');
  const [editingCategoryId, setEditingCategoryId] = useState('');
  const dashboard = useQuery({
    ...siteHealthQueries.dashboard(projectId),
    refetchInterval: query.data ? ACTIVE_RUN_POLL_MS : false,
  });
  const catalogMutation = useMutation({
    mutationFn: async (file: File) =>
      commerceApi.importCatalog(projectId, await file.text(), file.name),
    onSuccess: async (data) => {
      setResult(
        `${data.created} created, ${data.updated} updated, ${data.unchanged} unchanged, ${data.rejected} rejected.`,
      );
      await client.invalidateQueries({ queryKey: queryKeys.commerce.catalog(projectId) });
    },
  });
  const discover = useMutation({
    mutationFn: () => siteHealthApi.createCrawl({ project_id: projectId }),
    onSuccess: async () => {
      await Promise.all([dashboard.refetch(), query.refetch()]);
    },
  });
  if (query.isLoading) return <p>Loading persisted catalog…</p>;
  if (query.isError || !query.data)
    return <Alert tone="danger">The catalog could not be loaded.</Alert>;
  const crawl = dashboard.data?.crawl;
  const refresh = () => void Promise.all([dashboard.refetch(), query.refetch()]);
  return (
    <div className="grid gap-4">
      <CatalogHeader
        crawl={crawl}
        tasks={query.data.projection_tasks}
        discoverPending={discover.isPending}
        dashboardPending={dashboard.isPending}
        siteHealthError={discover.isError || dashboard.isError}
        importPending={catalogMutation.isPending}
        importError={catalogMutation.isError}
        result={result}
        onSiteHealthAction={() => (crawl ? refresh() : discover.mutate())}
        onImport={(file) => catalogMutation.mutate(file)}
      />
      <Card>
        <CardHeader>
          <CardTitle>Categories</CardTitle>
          <CardDescription>{query.data.categories.length} persisted categories</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Category</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Products</TableHead>
                <TableHead>Correction</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.categories.map((category) => (
                <TableRow key={category.id}>
                  <TableCell>
                    {category.name}
                    {editingCategoryId === category.id ? (
                      <CategoryEditor
                        projectId={projectId}
                        category={category}
                        onDone={() => setEditingCategoryId('')}
                      />
                    ) : null}
                  </TableCell>
                  <TableCell>{category.role}</TableCell>
                  <TableCell>{category.product_count}</TableCell>
                  <TableCell>
                    <Button size="sm" onClick={() => setEditingCategoryId(category.id)}>
                      Rename
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Products</CardTitle>
          <CardDescription>{query.data.products.length} canonical PDPs</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Product</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Brand</TableHead>
                <TableHead>Price</TableHead>
                <TableHead>Correction</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.products.map((product) => (
                <TableRow key={product.id}>
                  <TableCell>
                    <a className="text-link" href={product.canonical_url}>
                      {product.name || product.canonical_url}
                    </a>
                    {editingId === product.id ? (
                      <ProductEditor
                        projectId={projectId}
                        product={product}
                        catalog={query.data}
                        onDone={() => setEditingId('')}
                      />
                    ) : null}
                  </TableCell>
                  <TableCell>{categoryNames(product, query.data)}</TableCell>
                  <TableCell>{product.brand || 'Unknown'}</TableCell>
                  <TableCell>
                    {product.price == null ? 'Unknown' : `${product.currency} ${product.price}`}
                  </TableCell>
                  <TableCell>
                    <Button size="sm" onClick={() => setEditingId(product.id)}>
                      Edit
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
