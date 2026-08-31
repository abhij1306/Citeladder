'use client';

import { useRef, useState, type MutableRefObject } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { CursorPager } from '@/components/ui/cursor-pager';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { queryKeys } from '@/lib/api/query-keys';
import { siteHealthMutations, siteHealthQueries } from '@/lib/api/site-health';
import type { IssueHistoryPage, PageDetail } from '@/lib/api/types';
import { ApiError } from '@/lib/api/errors';
import { RERUN_MAX_PRE_ACTIVE_POLLS, RERUN_POLL_INTERVAL_MS } from '@/lib/config/site-health';
import {
  dimensionLabel,
  issueTitle,
  severityBadgeValue,
  severityLabel,
} from '@/lib/site-health/issues';
import { formatAudited } from '@/lib/site-health/status';
import { cn } from '@/lib/utils';

import { UrlDetailView } from './url-detail-view';

const HISTORY_LIMIT = 25;
const RERUN_SEARCH_PARAM = 'rerun';

/** Query and rerun controller for a crawl-bounded Site Health URL detail. */
export function UrlDetail({
  crawlId,
  siteUrlId,
}: Readonly<{ crawlId: string; siteUrlId: string }>) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  // A rerun that minted a NEW crawl navigates here with `?rerun=1`; start
  // polling on mount so the fresh run's queued/running progress is observed
  // without a manual reload.
  const [rerunPolling, setRerunPolling] = useState(
    () => searchParams.get(RERUN_SEARCH_PARAM) === '1',
  );
  // The cache can still hold the prior terminal snapshot immediately after a
  // rerun succeeds. Polling must continue until the fresh queued/running state
  // has been observed, rather than treating that stale terminal status as done.
  const hasObservedActiveRerunRef = useRef(false);
  const preActivePollCountRef = useRef(0);
  const [rerunQueued, setRerunQueued] = useState(false);
  const [rerunError, setRerunError] = useState<string | null>(null);
  const detailQuery = useQuery({
    ...siteHealthQueries.page(crawlId, siteUrlId),
    refetchInterval: (query) =>
      rerunPollInterval(
        rerunPolling,
        query.state.data?.analysis_status,
        hasObservedActiveRerunRef,
        preActivePollCountRef,
      ),
  });
  const rerun = useMutation({
    ...siteHealthMutations.rerunPage(),
    onSuccess: async (result) => {
      if (result.crawl_id === crawlId && result.site_url_id === siteUrlId) {
        // Invalidate before enabling polling: setting polling first can observe
        // the stale terminal cache entry and stop before the invalidation fetch
        // returns the newly enqueued pending/running snapshot.
        await queryClient.invalidateQueries({
          queryKey: queryKeys.siteHealth.page(crawlId, siteUrlId),
        });
        hasObservedActiveRerunRef.current = false;
        preActivePollCountRef.current = 0;
        setRerunQueued(true);
        setRerunPolling(true);
        return;
      }
      queryClient.setQueryData<PageDetail>(
        queryKeys.siteHealth.page(result.crawl_id, result.site_url_id),
        (previous) =>
          previous
            ? { ...previous, crawl_id: result.crawl_id, analysis_status: result.analysis_status }
            : previous,
      );
      router.push(
        `/site/crawls/${result.crawl_id}/pages/${result.site_url_id}?${RERUN_SEARCH_PARAM}=1`,
      );
    },
    onError: (error) => setRerunError(rerunErrorMessage(error)),
  });

  if (detailQuery.isLoading) return <DetailSkeleton />;
  if (detailQuery.isError || !detailQuery.data) {
    return <Alert tone="danger">Could not load this page. It may not exist in this crawl.</Alert>;
  }

  return (
    <div className="grid gap-[var(--workspace-gap)]">
      <UrlDetailView
        detail={detailQuery.data}
        rerunPending={rerun.isPending}
        rerunQueued={rerunQueued}
        onRerun={() => {
          setRerunError(null);
          rerun.mutate({ crawlId, siteUrlId });
        }}
      />
      {rerunError ? <Alert tone="danger">{rerunError}</Alert> : null}
      <IssueHistory
        key={`history:${crawlId}:${siteUrlId}`}
        crawlId={crawlId}
        siteUrlId={siteUrlId}
      />
    </div>
  );
}

function rerunPollInterval(
  polling: boolean,
  status: PageDetail['analysis_status'] | undefined,
  observedActive: MutableRefObject<boolean>,
  preActivePollCount: MutableRefObject<number>,
): number | false {
  if (!polling) return false;
  if (status === 'pending' || status === 'running') {
    observedActive.current = true;
    preActivePollCount.current = 0;
    return RERUN_POLL_INTERVAL_MS;
  }
  if (status === undefined || !observedActive.current) {
    if (preActivePollCount.current >= RERUN_MAX_PRE_ACTIVE_POLLS) return false;
    preActivePollCount.current += 1;
    return RERUN_POLL_INTERVAL_MS;
  }
  return false;
}

function rerunErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return 'This page is not in your monitored set — add it before re-auditing.';
  }
  if (error instanceof ApiError && error.status === 403)
    return 'Re-auditing pages requires a Starter plan.';
  return 'Could not re-audit this page. Please try again.';
}

function DetailSkeleton() {
  return (
    <div className="grid gap-[var(--workspace-gap)]">
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

function IssueHistory({ crawlId, siteUrlId }: Readonly<{ crawlId: string; siteUrlId: string }>) {
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const cursor = cursorStack.at(-1);
  const historyQuery = useQuery(
    siteHealthQueries.issueHistory(crawlId, siteUrlId, { cursor, limit: HISTORY_LIMIT }),
  );
  const rows = historyQuery.data?.items ?? [];
  const nextCursor = historyQuery.data?.next_cursor ?? null;

  return (
    <Card>
      <CardContent className="grid gap-3">
        <h2 className="text-foreground text-base font-medium tracking-[-0.015em]">Issue History</h2>
        {historyQuery.isError ? <Alert tone="danger">Could not load issue history.</Alert> : null}
        {historyQuery.isLoading ? <HistorySkeleton /> : null}
        {!historyQuery.isLoading && !historyQuery.isError && rows.length === 0 ? (
          <p className="text-secondary text-sm">No prior issue records for this page.</p>
        ) : null}
        {rows.length > 0 ? <HistoryRows rows={rows} /> : null}
        {rows.length > 0 ? (
          <div className="flex justify-end">
            <CursorPager
              canPrev={cursorStack.length > 0}
              canNext={Boolean(nextCursor)}
              onPrev={() => setCursorStack((previous) => previous.slice(0, -1))}
              onNext={() =>
                nextCursor &&
                setCursorStack((previous) =>
                  previous.at(-1) === nextCursor ? previous : [...previous, nextCursor],
                )
              }
            />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function HistorySkeleton() {
  return (
    <div className="grid gap-2">
      <Skeleton className="h-6 w-full" />
      <Skeleton className="h-6 w-full" />
    </div>
  );
}

function HistoryRows({ rows }: Readonly<{ rows: IssueHistoryPage['items'] }>) {
  return (
    <ul className="divide-border-subtle divide-y">
      {rows.map((row) => (
        <li key={row.id} className="flex items-center justify-between gap-3 py-2">
          <span className="flex min-w-0 flex-col">
            <span className="text-foreground truncate text-sm">{issueTitle(row)}</span>
            <span className="text-muted font-mono text-xs">{formatAudited(row.created_at)}</span>
          </span>
          <span className="flex shrink-0 items-center gap-2">
            <Badge className={cn(row.dimension === 'aeo' ? 'text-accent-text' : 'text-info-text')}>
              {dimensionLabel(row.dimension)}
            </Badge>
            <Badge variant="status" value={severityBadgeValue(row.severity)}>
              {severityLabel(row.severity)}
            </Badge>
          </span>
        </li>
      ))}
    </ul>
  );
}
