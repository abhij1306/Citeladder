'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';

import { OpportunityEvidenceSection } from '@/components/opportunities/opportunity-evidence-section';
import { OpportunityStatusBadge } from '@/components/opportunities/opportunity-status-badge';
import { OpportunityStatusFooter } from '@/components/opportunities/opportunity-status-footer';
import { OpportunitySummarySection } from '@/components/opportunities/opportunity-summary-section';
import { OpportunityTypeBadge } from '@/components/opportunities/opportunity-type-badge';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Drawer } from '@/components/ui/drawer';
import { Skeleton } from '@/components/ui/skeleton';
import { Label } from '@/components/ui/typography';
import { opportunitiesMutations, opportunitiesQueries } from '@/lib/api/opportunities';
import { queryKeys } from '@/lib/api/query-keys';
import { severityBadgeValue, severityLabel } from '@/lib/site-health/issues';

/** Recommendation detail drawer backed by the persisted detail projection. */
export function EvidenceDrawer({
  opportunityId,
  projectId,
  open,
  onOpenChange,
}: Readonly<{
  opportunityId: string | null;
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}>) {
  const detailQuery = useQuery({
    ...opportunitiesQueries.detail(opportunityId ?? ''),
    enabled: open && opportunityId !== null,
  });
  const detail = detailQuery.data ?? null;
  const queryClient = useQueryClient();
  const guidanceQuery = useQuery({
    ...opportunitiesQueries.guidance(opportunityId ?? ''),
    enabled: open && opportunityId !== null,
    retry: false,
  });
  const guidanceMutation = useMutation({
    ...opportunitiesMutations.createGuidance(),
    onSuccess: (guidance) => {
      queryClient.setQueryData(queryKeys.opportunities.guidance(guidance.opportunity_id), guidance);
    },
  });

  const createGuidance = () => {
    if (!opportunityId) return;
    guidanceMutation.mutate({ opportunityId, idempotencyKey: crypto.randomUUID() });
  };
  let guidanceActionLabel = 'Generate';
  if (guidanceQuery.data) guidanceActionLabel = 'Regenerate';
  if (guidanceMutation.isPending) guidanceActionLabel = 'Generating…';

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Opportunity detail"
      className="max-w-112"
      bodyClassName="px-4"
      footer={detail ? <OpportunityStatusFooter detail={detail} projectId={projectId} /> : null}
    >
      {detailQuery.isError ? (
        <Alert tone="danger">Could not load this opportunity. Please try again.</Alert>
      ) : detailQuery.isLoading || !detail ? (
        <div className="grid gap-3">
          <Skeleton className="h-8 w-3/4" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : (
        <div className="grid gap-5">
          <div className="grid gap-2">
            <h2 className="text-foreground text-lg">{detail.title}</h2>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant="status" value={severityBadgeValue(detail.severity)}>
                {severityLabel(detail.severity)} impact
              </Badge>
              <OpportunityTypeBadge type={detail.opportunity_type} />
              <OpportunityStatusBadge status={detail.status} />
            </div>
          </div>
          <OpportunityEvidenceSection detail={detail} />
          {detail.remediation ? (
            <section className="grid gap-2">
              <Label>Recommended improvements</Label>
              <div className="border-border-subtle bg-background-alt rounded-lg border p-3">
                <p className="text-foreground text-sm whitespace-pre-line">{detail.remediation}</p>
              </div>
            </section>
          ) : null}
          <Button variant="secondary" size="sm" asChild>
            <Link href={`/content?opportunity_id=${detail.id}`}>
              Create content from this opportunity
            </Link>
          </Button>
          <section className="grid gap-2">
            <div className="flex items-center justify-between gap-2">
              <Label>Tailored guidance</Label>
              <Button
                size="sm"
                variant="secondary"
                onClick={createGuidance}
                disabled={guidanceMutation.isPending}
              >
                {guidanceActionLabel}
              </Button>
            </div>
            {guidanceQuery.data ? (
              <div className="border-border-subtle bg-background-alt grid gap-3 rounded-lg border p-3">
                <div className="grid gap-1">
                  <span className="text-2xs text-muted">What was found</span>
                  <ul className="text-foreground grid list-disc gap-1 pl-4 text-sm">
                    {guidanceQuery.data.findings.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
                <div className="grid gap-1">
                  <span className="text-2xs text-muted">Recommended improvements</span>
                  <ul className="text-foreground grid list-disc gap-1 pl-4 text-sm">
                    {guidanceQuery.data.recommendations.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
                <p className="text-muted text-xs">
                  Updated {new Date(guidanceQuery.data.created_at).toLocaleString()}
                </p>
              </div>
            ) : guidanceQuery.isError ? (
              <Alert tone="info">Tailored guidance is unavailable for this workspace.</Alert>
            ) : null}
            {guidanceMutation.isError ? (
              <Alert tone="danger">Could not generate guidance. Please try again.</Alert>
            ) : null}
          </section>
          <OpportunitySummarySection detail={detail} />
        </div>
      )}
    </Drawer>
  );
}
