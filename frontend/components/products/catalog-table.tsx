'use client';

import Link from 'next/link';
import { MoreHorizontal, Pencil, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownSeparator,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { TablePagination, useTablePage } from '@/components/ui/table-pagination';
import { Tooltip } from '@/components/ui/tooltip';
import type { IntegrationSyncRun } from '@/lib/api/integrations';
import type { CommerceCatalogHealth, Product, ProductCompleteness } from '@/lib/api/types';
import {
  completenessHoverDetail,
  feedHealthDisplay,
  feedHealthLabel,
  formatPrice,
  PRODUCT_ORIGIN_LABELS,
} from '@/lib/products/catalog';

import { SyncCell } from './catalog-table-sync-cell';

/** Rows per page on the catalog table (client-side; the list arrives whole). */
const PAGE_SIZE = 10;

/**
 * Catalog table (Commerce workspace). Dense SKU table with columns product
 * (name + first variant), sku, price, variants count, completeness badge
 * (missing attributes in a tooltip), origin badge (Manual / CSV import /
 * Synced feed), per-SKU feed health joined from the catalog-health
 * projection by `product_id` (never by mutable display name), and the bound
 * connection's sync state, plus per-row edit/delete actions. The product
 * name links to the `/products/[productId]` evidence drill-down. Purely
 * presentational — CRUD and sync polling are owned by the catalog panel.
 */
export function CatalogTable({
  products,
  health = null,
  healthPending = false,
  syncOverrides = {},
  onEdit,
  onDelete,
}: Readonly<{
  products: Product[];
  /** The catalog-health projection (null while unavailable/failed). */
  health?: CommerceCatalogHealth | null;
  /** True while the health projection is still loading. */
  healthPending?: boolean;
  /** Freshest polled sync runs, keyed by connection id. */
  syncOverrides?: Readonly<Record<string, IntegrationSyncRun>>;
  onEdit: (product: Product) => void;
  onDelete: (product: Product) => void;
}>) {
  const { page, setPage, pageCount, from, to } = useTablePage(products.length, PAGE_SIZE);
  const pagedProducts = products.slice(from - 1, to);

  const healthByProductId = new Map(
    (health?.products ?? [])
      .filter((row) => row.product_id !== null)
      .map((row) => [row.product_id as string, row]),
  );
  const connectionById = new Map(
    (health?.connections ?? []).map((connection) => [connection.connection_id, connection]),
  );

  return (
    <div className="bg-panel shadow-card overflow-hidden rounded-lg">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Product</TableHead>
            <TableHead>SKU</TableHead>
            <TableHead>Price</TableHead>
            <TableHead>Variants</TableHead>
            <TableHead>Attributes</TableHead>
            <TableHead>Origin</TableHead>
            <TableHead>Feed health</TableHead>
            <TableHead>Sync</TableHead>
            <TableHead className="w-16 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {pagedProducts.map((product) => (
            <TableRow key={product.id}>
              <TableCell className="max-w-80 min-w-50">
                <div className="grid gap-0.5">
                  <Link
                    href={`/products/${product.id}`}
                    className="text-foreground hover:text-accent-text truncate font-medium transition-colors"
                  >
                    {product.name}
                  </Link>
                  {product.variants[0]?.name ? (
                    <span className="text-muted truncate text-xs">{product.variants[0].name}</span>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="text-secondary font-mono text-xs">{product.sku}</TableCell>
              <TableCell numeric className="text-secondary">
                {formatPrice(product.price, product.currency)}
              </TableCell>
              <TableCell numeric className="text-secondary">
                {product.variants.length > 0 ? product.variants.length : '—'}
              </TableCell>
              <TableCell>
                <CompletenessBadge completeness={product.completeness} />
              </TableCell>
              <TableCell>
                <OriginBadge origin={product.origin} />
              </TableCell>
              <TableCell>
                <FeedHealthCell
                  product={product}
                  healthRow={healthByProductId.get(product.id)}
                  pending={healthPending}
                />
              </TableCell>
              <TableCell>
                <SyncCell
                  product={product}
                  connection={
                    product.connection_id ? connectionById.get(product.connection_id) : undefined
                  }
                  override={
                    product.connection_id ? syncOverrides[product.connection_id] : undefined
                  }
                  pending={healthPending}
                />
              </TableCell>
              <TableCell className="text-right">
                <Dropdown>
                  <DropdownTrigger asChild>
                    <Button variant="ghost" size="icon" aria-label={`Actions for ${product.name}`}>
                      <MoreHorizontal className="size-4" aria-hidden />
                    </Button>
                  </DropdownTrigger>
                  <DropdownContent align="end">
                    <DropdownItem onSelect={() => onEdit(product)}>
                      <Pencil className="size-4" aria-hidden />
                      Edit
                    </DropdownItem>
                    <DropdownSeparator />
                    <DropdownItem
                      onSelect={() => onDelete(product)}
                      className="text-danger-text data-[highlighted]:bg-danger-bg"
                    >
                      <Trash2 className="size-4" aria-hidden />
                      Delete
                    </DropdownItem>
                  </DropdownContent>
                </Dropdown>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <TablePagination
        page={page}
        pageCount={pageCount}
        from={from}
        to={to}
        total={products.length}
        noun="products"
        onPageChange={setPage}
      />
    </div>
  );
}

/**
 * The data-quality badge: `12/12` (success when complete, neutral otherwise)
 * — the badge is never color-only (the `N missing` text carries the
 * meaning). EVERY row carries the per-SKU hover detail (D4): the feed
 * completeness score plus, for incomplete rows, the human-labelled missing
 * attributes (all from the `completeness` payload).
 */
function CompletenessBadge({ completeness }: Readonly<{ completeness: ProductCompleteness }>) {
  const complete = completeness.missing.length === 0;
  const label = `${completeness.present}/${completeness.total}`;
  const badge = complete ? (
    <Badge variant="status" value="success">
      {label} · Complete
    </Badge>
  ) : (
    <Badge variant="status" value="warning">
      {label} · {completeness.missing.length} missing
    </Badge>
  );
  return <Tooltip content={completenessHoverDetail(completeness)}>{badge}</Tooltip>;
}

/** Origin badge: explicit text for manual / CSV-imported / feed-synced rows. */
function OriginBadge({ origin }: Readonly<{ origin: Product['origin'] }>) {
  if (origin === 'synced') {
    return (
      <Badge variant="status" value="info">
        {PRODUCT_ORIGIN_LABELS[origin]}
      </Badge>
    );
  }
  return <Badge variant="neutral">{PRODUCT_ORIGIN_LABELS[origin]}</Badge>;
}

/**
 * Feed-health cell (joined by `product_id`): a status badge whose text
 * carries the meaning (`Healthy` / `N warnings` / `N errors` / `Unavailable`)
 * with the non-secret rule ids in a tooltip; unbound and unprojected rows
 * get explicit muted text instead of implying a feed error.
 */
function FeedHealthCell({
  product,
  healthRow,
  pending,
}: Readonly<{
  product: Product;
  healthRow: CommerceCatalogHealth['products'][number] | undefined;
  pending: boolean;
}>) {
  if (pending) {
    return <span className="text-subtle text-xs">…</span>;
  }
  const display = feedHealthDisplay(product, healthRow);
  const label = feedHealthLabel(display);
  if (display.kind !== 'status') {
    return <span className="text-muted text-xs">{label}</span>;
  }
  const badge =
    display.status === 'healthy' ? (
      <Badge variant="status" value="success">
        {label}
      </Badge>
    ) : display.status === 'warning' ? (
      <Badge variant="status" value="warning">
        {label}
      </Badge>
    ) : display.status === 'error' ? (
      <Badge variant="status" value="danger">
        {label}
      </Badge>
    ) : (
      <Badge variant="neutral">{label}</Badge>
    );
  if (display.ruleIds.length === 0) return badge;
  return <Tooltip content={display.ruleIds.join(', ')}>{badge}</Tooltip>;
}
