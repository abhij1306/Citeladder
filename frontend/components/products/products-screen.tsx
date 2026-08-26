'use client';

import { Alert } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useProjectContext } from '@/lib/project/project-context';
import { useCommerceQueries, useProductsTab } from '@/lib/products/use-products-screen';

import { BuyerPromptsPanel, CatalogPanel, CompetitorsPanel, ShelfPanel } from './commerce-panels';
import { ProductsTabs } from './products-tabs';

export function ProductsScreenSkeleton() {
  return (
    <Card aria-hidden>
      <CardContent>
        <Skeleton className="h-48 w-full" />
      </CardContent>
    </Card>
  );
}

export function ProductsScreen() {
  const { activeProject, isLoading } = useProjectContext();
  const { activeTab, selectTab } = useProductsTab();
  const projectId = activeProject?.id ?? '';
  const queries = useCommerceQueries(projectId, activeTab);
  if (isLoading) return <ProductsScreenSkeleton />;
  if (!projectId) return <Alert tone="info">Select or create a project to use Commerce.</Alert>;
  const panel =
    activeTab === 'catalog' ? (
      <CatalogPanel projectId={projectId} query={queries.catalog} />
    ) : activeTab === 'competitors' ? (
      <CompetitorsPanel projectId={projectId} queries={queries} />
    ) : activeTab === 'buyer-prompts' ? (
      <BuyerPromptsPanel projectId={projectId} queries={queries} />
    ) : (
      <ShelfPanel query={queries.shelf} />
    );
  return <ProductsTabs activeTab={activeTab} onSelectTab={selectTab} panel={panel} />;
}
