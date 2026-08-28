'use client';

import { useParams } from 'next/navigation';
import { Suspense } from 'react';

import { UrlDetail } from '@/components/site-health/url-detail';
import { Skeleton } from '@/components/ui/skeleton';

/** Canonical crawl-bounded Website page detail. */
export default function UrlDetailPage() {
  const params = useParams<{ crawlId: string; siteUrlId: string }>();
  return (
    <Suspense
      fallback={
        <div className="grid gap-[var(--workspace-gap)]" aria-hidden>
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      }
    >
      <UrlDetail crawlId={params.crawlId} siteUrlId={params.siteUrlId} />
    </Suspense>
  );
}
