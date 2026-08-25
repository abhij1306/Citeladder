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
import type { Product, ProductCompleteness } from '@/lib/api/types';
import { completenessHoverDetail, formatPrice } from '@/lib/products/catalog';

/** Rows per page on the catalog table (client-side; the list arrives whole). */
const PAGE_SIZE = 10;

function variantCount(product: Product): number {
  const persisted = Number(product.attributes.variant_count);
  return Number.isInteger(persisted) && persisted >= 0 ? persisted : product.variants.length;
}

/**
 * Catalog table (Commerce workspace). Dense SKU table with columns product
 * (name + first variant), sku, price, variants count, completeness badge
 * (missing attributes in a tooltip), and per-row edit/delete actions. The product
 * name links to the `/products/[productId]` evidence drill-down. Purely
 * presentational — CRUD is owned by the catalog panel.
 */
export function CatalogTable({
  products,
  onEdit,
  onDelete,
}: Readonly<{
  products: Product[];
  onEdit: (product: Product) => void;
  onDelete: (product: Product) => void;
}>) {
  const { page, setPage, pageCount, from, to } = useTablePage(products.length, PAGE_SIZE);
  const pagedProducts = products.slice(from - 1, to);

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
                {variantCount(product) || '—'}
              </TableCell>
              <TableCell>
                <CompletenessBadge completeness={product.completeness} />
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
