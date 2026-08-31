'use client';

import { useQuery } from '@tanstack/react-query';
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
import { opportunitiesQueries } from '@/lib/api/opportunities';
import type { OpportunityDetail } from '@/lib/api/types';
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

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Opportunity detail"
      className="sm:max-w-160"
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
        <div className="grid gap-4">
          <div className="grid gap-2.5">
            <h2 className="font-display text-foreground text-base leading-snug font-semibold tracking-tight">
              {detail.title}
            </h2>
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
              <div className="border-border-subtle bg-well rounded-[var(--radius-control)] border p-3">
                <p className="text-secondary text-sm leading-relaxed whitespace-pre-line">
                  {detail.remediation}
                </p>
              </div>
            </section>
          ) : null}
          <OpportunitySummarySection detail={detail} />
          <ActionHandoff detail={detail} />
        </div>
      )}
    </Drawer>
  );
}

function ActionHandoff({ detail }: Readonly<{ detail: OpportunityDetail }>) {
  const handoff = detail.content_handoff;
  const earned = handoff.pathway === 'earned';
  const generationLabel = detail.linked_generations.length === 1 ? 'generation' : 'generations';
  return (
    <section className="grid gap-2">
      <Label>Action handoff</Label>
      <div className="border-border-subtle bg-panel grid gap-2 rounded-md border p-3">
        <p className="text-secondary text-sm">
          {earned
            ? `Prepare a human-led earned asset for ${handoff.canonical_domain ?? 'the cited source'}.`
            : 'Create or improve content the brand controls.'}
        </p>
        {handoff.limitations.map((limitation) => (
          <p key={limitation} className="text-muted text-xs">
            {limitation}
          </p>
        ))}
        <Button asChild size="sm" className="justify-self-start">
          <Link href={`/content?opportunity_id=${detail.id}`}>
            {earned ? 'Prepare earned content' : 'Create owned content'}
          </Link>
        </Button>
        {detail.linked_generations.length > 0 ? (
          <p className="text-muted text-xs">
            {detail.linked_generations.length} linked {generationLabel}
          </p>
        ) : null}
      </div>
    </section>
  );
}
