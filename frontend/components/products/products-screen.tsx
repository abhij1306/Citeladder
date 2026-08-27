'use client';

import { Alert } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useProjectContext } from '@/lib/project/project-context';

import { CommerceWorkspace } from './commerce-workspace';

export function ProductsScreenSkeleton() {
  return (
    <Card aria-hidden>
      <CardContent>
        <Skeleton className="h-48 w-full" />
      </CardContent>
    </Card>
  );
}

/**
 * Commerce is one screen, not four tabs.
 *
 * The tabs were verbs — Catalog, Competitors, Buyer Prompts, AI Shelf — and
 * each one re-asked the same noun, so the target selector was duplicated three
 * times over three selection states that never agreed. The catalog is the
 * navigation now and everything else is a view of the selected target, held in
 * `?target=`. A legacy `?tab=` value is simply ignored, which lands on the
 * workspace rather than a route that no longer exists.
 */
export function ProductsScreen() {
  const { activeProject, isLoading } = useProjectContext();
  const projectId = activeProject?.id ?? '';
  if (isLoading) return <ProductsScreenSkeleton />;
  if (!projectId) return <Alert tone="info">Select or create a project to use Commerce.</Alert>;
  return <CommerceWorkspace projectId={projectId} />;
}
