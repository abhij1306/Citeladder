'use client';

import { useQuery } from '@tanstack/react-query';

import type { MutationNotice as MutationNoticeData } from '@/lib/api/mutation-notice';
import { productsApi } from '@/lib/api/products';
import { queryKeys } from '@/lib/api/query-keys';
import type { Product } from '@/lib/api/types';

import { ProductDeleteDialogView } from './product-delete-dialog-view';

/** Delete confirmation controller. The audit-reference check blocks only while pending. */
export function ProductDeleteDialog({
  product,
  open,
  onOpenChange,
  onConfirm,
  isDeleting,
  notice,
}: Readonly<{
  product: Product | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => Promise<void> | void;
  isDeleting?: boolean;
  notice?: MutationNoticeData;
}>) {
  const enabled = open && product !== null;
  const referencesQuery = useQuery({
    queryKey: queryKeys.products.auditReferences(product?.id ?? ''),
    queryFn: ({ signal }) => productsApi.getAuditReferences(product!.id, { signal }),
    enabled,
  });
  const checking = enabled && referencesQuery.isPending;
  const auditCount = referencesQuery.data?.referenced ? referencesQuery.data.audit_count : null;

  return (
    <ProductDeleteDialogView
      product={product}
      open={open}
      onOpenChange={onOpenChange}
      onConfirm={onConfirm}
      isDeleting={isDeleting}
      notice={notice}
      checking={checking}
      auditCount={auditCount}
    />
  );
}
