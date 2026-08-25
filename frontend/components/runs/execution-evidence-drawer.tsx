'use client';

import { useQuery } from '@tanstack/react-query';

import { EvidenceCard } from '@/components/runs/evidence-card';
import { Alert } from '@/components/ui/alert';
import { Drawer } from '@/components/ui/drawer';
import { Skeleton } from '@/components/ui/skeleton';
import { queryKeys } from '@/lib/api/query-keys';
import { runsApi } from '@/lib/api/runs';
import type { Execution } from '@/lib/api/types';

/** Persisted execution evidence shown without leaving the run detail context. */
export function ExecutionEvidenceDrawer({
  execution,
  open,
  onOpenChange,
}: Readonly<{
  execution: Execution | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}>) {
  const evidenceQuery = useQuery({
    queryKey: queryKeys.runs.execution(execution?.id ?? ''),
    queryFn: ({ signal }) => runsApi.getExecution(execution?.id ?? '', { signal }),
    enabled: open && execution !== null,
  });

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Execution evidence"
      description={
        execution
          ? `Prompt #${execution.prompt_index + 1} · repetition ${execution.repetition}`
          : undefined
      }
      closeLabel="Close evidence drawer"
    >
      {evidenceQuery.isError ? (
        <Alert tone="danger">Could not load this execution&apos;s evidence.</Alert>
      ) : evidenceQuery.isLoading || !evidenceQuery.data ? (
        <div className="grid gap-4" aria-label="Loading execution evidence">
          <Skeleton className="h-10 w-2/3" />
          <Skeleton className="h-44 w-full" />
          <Skeleton className="h-52 w-full" />
        </div>
      ) : (
        <EvidenceCard
          evidence={evidenceQuery.data}
          answerText={execution?.answer_text}
          promptText={execution?.prompt_text}
          promptIndex={execution?.prompt_index}
          repetition={execution?.repetition}
        />
      )}
    </Drawer>
  );
}
