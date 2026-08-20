'use client';

import { Suspense } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';
import { ProductsScreen, ProductsScreenSkeleton } from '@/components/products/products-screen';

/**
 * Commerce workspace: Overview, Catalog, AI Visibility, Competitors, and
 * Opportunities. Overview is the default and every tab reads persisted data.
 * The active tab is mirrored in `?tab=`. The page title renders in the top
 * bar (F5), so there is no in-page header block.
 */
export default function ProductsPage() {
  return (
    <TooltipProvider>
      <div className="grid gap-6">
        <Suspense fallback={<ProductsScreenSkeleton />}>
          <ProductsScreen />
        </Suspense>
      </div>
    </TooltipProvider>
  );
}
