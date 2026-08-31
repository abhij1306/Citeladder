'use client';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import { engineLabel, transportLabel } from '@/lib/providers/catalog';
import type { Execution } from '@/lib/api/types';
import { executionBadgeValue, executionStatusLabel } from '@/lib/runs/status';

/**
 * Executions table for a run (F10, design.md §9.7).
 *
 * One row per execution/queue task: prompt index + repetition (mono), the
 * engine badge (logical + transport), status badge, and latency (mono).
 * Succeeded rows open the evidence drawer without leaving the run.
 */
export function ExecutionsTable({
  executions,
  onSelectEvidence,
}: Readonly<{ executions: Execution[]; onSelectEvidence: (execution: Execution) => void }>) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Prompt</TableHead>
          <TableHead>Engine</TableHead>
          <TableHead>Status</TableHead>
          <TableHead numeric>Latency</TableHead>
          <TableHead className="sr-only">Evidence</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {executions.map((execution) => (
          <TableRow key={execution.id}>
            <TableCell className="max-w-2xl py-3">
              <div className="flex flex-col gap-1">
                <span
                  className="text-foreground text-sm leading-relaxed font-normal break-words"
                  title={execution.prompt_text}
                >
                  {execution.prompt_text || `Prompt #${execution.prompt_index + 1}`}
                </span>
                <span className="mono text-muted text-xs">rep {execution.repetition}</span>
              </div>
            </TableCell>
            <TableCell className="py-3">
              <span className="text-foreground text-sm font-medium">
                {engineLabel(execution.logical_engine)}
              </span>
              <span className="text-muted ml-1.5 text-xs">
                {transportLabel(execution.transport_provider)}
              </span>
            </TableCell>
            <TableCell className="py-3">
              <Badge variant="status" value={executionBadgeValue(execution.status)}>
                {executionStatusLabel(execution.status)}
              </Badge>
            </TableCell>
            <TableCell numeric className="mono py-3">
              {execution.latency_ms == null ? (
                <UnavailableValue state="not_measured" />
              ) : (
                `${execution.latency_ms} ms`
              )}
            </TableCell>
            <TableCell className="py-3 text-right">
              {execution.status === 'succeeded' ? (
                <Button variant="ghost" size="sm" onClick={() => onSelectEvidence(execution)}>
                  Evidence
                </Button>
              ) : (
                <UnavailableValue state="unavailable" />
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
