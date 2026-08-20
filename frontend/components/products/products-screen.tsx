'use client';

import { Alert } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useProjectContext } from '@/lib/project/project-context';
import {
  useCatalogQueries,
  useCommerceComparison,
  useCommerceOpportunities,
  useCommerceOverview,
  useProductsTab,
  useProductVisibilityQueries,
} from '@/lib/products/use-products-screen';

import { AiVisibilityPanel } from './ai-visibility-panel';
import { CatalogPanel } from './catalog-panel';
import { CommerceOpportunitiesPanel } from './commerce-opportunities-panel';
import { CommerceOverviewPanel } from './commerce-overview-panel';
import { CompetitorsPanel } from './competitors-panel';
import { ProductsTabs } from './products-tabs';

export function ProductsScreenSkeleton() {
  return (
    <div className="grid gap-4" aria-hidden>
      <Skeleton className="h-8 w-72" />
      <Card>
        <CardContent>
          <Skeleton className="h-48 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}

/** Five-tab Commerce suite. Every inactive tab remains query-inert. */
export function ProductsScreen() {
  const { activeProject, isLoading: isProjectLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;
  const { activeTab, selectTab } = useProductsTab();
  const overviewQueries = useCommerceOverview(projectId, activeTab === 'overview');
  const catalogQueries = useCatalogQueries(projectId, activeTab === 'catalog');
  const visibilityQueries = useProductVisibilityQueries(projectId, activeTab === 'visibility');
  const comparisonQueries = useCommerceComparison(projectId, activeTab === 'competitors');
  const opportunityQueries = useCommerceOpportunities(projectId, activeTab === 'opportunities');

  if (isProjectLoading) return <ProductsScreenSkeleton />;
  if (!projectId)
    return <Alert tone="info">Select or create a project to manage its product catalog.</Alert>;

  const panel =
    activeTab === 'catalog' ? (
      <CatalogPanel projectId={projectId} queries={catalogQueries} />
    ) : activeTab === 'visibility' ? (
      <AiVisibilityPanel projectId={projectId} queries={visibilityQueries} />
    ) : activeTab === 'competitors' ? (
      <CompetitorsPanel queries={comparisonQueries} />
    ) : activeTab === 'opportunities' ? (
      <CommerceOpportunitiesPanel queries={opportunityQueries} />
    ) : (
      <CommerceOverviewPanel queries={overviewQueries} onSelectTab={selectTab} />
    );

  return <ProductsTabs activeTab={activeTab} onSelectTab={selectTab} panel={panel} />;
}
