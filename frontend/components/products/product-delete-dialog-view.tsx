import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { MutationNotice } from '@/components/ui/mutation-notice';
import type { MutationNotice as MutationNoticeData } from '@/lib/api/mutation-notice';
import type { Product } from '@/lib/api/types';

export function ProductDeleteDialogView({
  product,
  open,
  onOpenChange,
  onConfirm,
  isDeleting,
  notice,
  checking,
  auditCount,
}: Readonly<{
  product: Product | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => Promise<void> | void;
  isDeleting?: boolean;
  notice?: MutationNoticeData;
  checking: boolean;
  auditCount: number | null;
}>) {
  const productName = product?.name ?? 'product';
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Delete ${productName}?`}
      description="This removes the product from the catalog. This cannot be undone."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={isDeleting}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => void onConfirm()}
            disabled={isDeleting || product === null || checking}
          >
            {isDeleting ? 'Deleting…' : checking ? 'Checking…' : 'Delete'}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 py-2">
        {notice ? <MutationNotice notice={notice} /> : null}
        {checking ? (
          <p className="text-muted text-sm" aria-live="polite">
            Checking whether any audits reference this product…
          </p>
        ) : null}
        {auditCount !== null ? (
          <Alert tone="warning">
            This product is frozen into {auditCount} audit configuration
            {auditCount === 1 ? '' : 's'}. Past runs keep their frozen copy and stay valid —
            deleting only stops future runs from measuring it.
          </Alert>
        ) : null}
        {product ? (
          <p className="text-secondary text-sm">
            <span className="text-foreground font-medium">{product.name}</span> (
            <span className="font-mono text-xs">{product.sku}</span>) will be removed from the
            catalog.
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}
