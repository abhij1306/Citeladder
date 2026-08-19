import Link from 'next/link';

import { Alert } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { SectionTitle } from '@/components/ui/typography';
import { ExecutionsTable } from '@/components/runs/executions-table';
import { ProgressPanel } from '@/components/runs/progress-panel';
import { humanizeApiError } from '@/lib/api/errors';
import type { MutationNotice } from '@/lib/api/mutation-notice';
import type { Audit, Execution } from '@/lib/api/types';

type RunDetailViewProps = {
  audit: Audit | undefined;
  auditLoading: boolean;
  auditError: unknown;
  executions: Execution[] | undefined;
  executionsLoading: boolean;
  executionsError: boolean;
  cancelPending: boolean;
  cancelNotice: MutationNotice | null;
  rerunPending: boolean;
  rerunNotice: MutationNotice | null;
  onCancel: () => void;
  onRerunFailures: () => void;
  onSelectEvidence: (execution: Execution) => void;
};

function AuditSection({
  audit,
  auditLoading,
  auditError,
  cancelPending,
  cancelNotice,
  rerunPending,
  rerunNotice,
  onCancel,
  onRerunFailures,
}: RunDetailViewProps) {
  if (auditError && !audit) {
    return <Alert tone="danger">{humanizeApiError(auditError).message}</Alert>;
  }
  if (auditLoading || !audit) {
    return (
      <Card>
        <CardContent className="grid gap-3">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-16 w-full" />
        </CardContent>
      </Card>
    );
  }
  return (
    <ProgressPanel
      audit={audit}
      onCancel={onCancel}
      cancelPending={cancelPending}
      cancelNotice={cancelNotice}
      onCancelRetry={onCancel}
      onRerunFailures={onRerunFailures}
      rerunPending={rerunPending}
      rerunNotice={rerunNotice}
      onRerunRetry={onRerunFailures}
    />
  );
}

function ExecutionsSection({
  executions,
  executionsLoading,
  executionsError,
  onSelectEvidence,
}: Pick<
  RunDetailViewProps,
  'executions' | 'executionsLoading' | 'executionsError' | 'onSelectEvidence'
>) {
  if (executionsError && !executions)
    return <Alert tone="danger">Could not load executions.</Alert>;
  if (executionsLoading || !executions) {
    return (
      <Card>
        <CardContent className="grid gap-3">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </CardContent>
      </Card>
    );
  }
  if (executions.length === 0) {
    return (
      <Card>
        <CardContent className="text-secondary py-8 text-center text-sm">
          No executions yet. They appear as the run is planned and processed.
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardContent className="p-0">
        <ExecutionsTable executions={executions} onSelectEvidence={onSelectEvidence} />
      </CardContent>
    </Card>
  );
}

export function RunDetailView(props: RunDetailViewProps) {
  return (
    <div className="grid gap-6">
      <Link href="/runs" className="text-accent-text text-xs font-medium hover:underline">
        ← Back to runs
      </Link>
      <AuditSection {...props} />
      <div className="grid gap-3">
        <SectionTitle>Executions</SectionTitle>
        <ExecutionsSection {...props} />
      </div>
    </div>
  );
}
