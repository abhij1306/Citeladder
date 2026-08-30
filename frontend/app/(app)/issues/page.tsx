import { Suspense } from 'react';

import { IssuesScreen } from '@/components/site-health/issues-screen';
import { Skeleton } from '@/components/ui/skeleton';

/**
 * Issues catalog (Slice 8, mockup 710).
 *
 * The grouped Site Health issue catalog for the active project's current crawl:
 * API-owned occurrence/severity/affected-page summaries, server-backed
 * search/filter/pagination, remediation, affected-URL navigation into the
 * per-URL detail, and client-only "copy fix prompt". There is no unsupported
 * "mark reviewed/resolved" persistence.
 */
export default function IssuesPage() {
  return (
    <Suspense
      fallback={
        <div className="grid gap-4">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      }
    >
      <IssuesScreen />
    </Suspense>
  );
}
