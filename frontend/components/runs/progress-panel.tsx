'use client';

import { Badge } from '@/components/ui/badge';
import { MeasurementContext } from '@/components/runs/measurement-context';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { MutationNotice } from '@/components/ui/mutation-notice';
import { Label, Metric } from '@/components/ui/typography';
import type { MutationNotice as MutationNoticeData } from '@/lib/api/mutation-notice';
import { runsApi } from '@/lib/api/runs';
import type { Audit } from '@/lib/api/types';
import {
  auditBadgeValue,
  auditStatusLabel,
  formatDateTime,
  isAuditCancelable,
  shouldPollAudit,
} from '@/lib/runs/status';

function ProgressHeader({
  audit,
  polling,
  cancelable,
  cancelPending,
  onCancel,
  onRerunFailures,
  rerunPending,
}: Readonly<{
  audit: Audit;
  polling: boolean;
  cancelable: boolean;
  cancelPending: boolean;
  onCancel: () => void;
  onRerunFailures?: () => void;
  rerunPending: boolean;
}>) {
  return (
    <div className="border-border-subtle flex flex-wrap items-center justify-between gap-3 border-b pb-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <Badge variant="run-status" value={auditBadgeValue(audit.status)}>
          {auditStatusLabel(audit.status)}
        </Badge>
        <MeasurementContext provenance={audit.model_provenance} />
        {polling ? (
          <span
            className="mono text-muted text-2xs inline-flex items-center gap-1.5"
            aria-live="polite"
          >
            <span
              className="bg-accent inline-block size-1.5 animate-pulse rounded-full"
              aria-hidden
            />
            Updating…
          </span>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" asChild>
          <a href={runsApi.exportUrl(audit.id, 'csv')} download>
            Export CSV
          </a>
        </Button>
        <Button variant="secondary" size="sm" asChild>
          <a href={runsApi.exportUrl(audit.id, 'md')} download>
            Export MD
          </a>
        </Button>
        <Button
          variant="destructive"
          size="sm"
          onClick={onCancel}
          disabled={!cancelable || cancelPending}
        >
          {cancelPending ? 'Cancelling…' : 'Cancel run'}
        </Button>
        {audit.failed_count > 0 && onRerunFailures ? (
          <Button variant="secondary" size="sm" onClick={onRerunFailures} disabled={rerunPending}>
            {rerunPending ? 'Creating repair…' : 'Rerun failed'}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function ProgressBar({
  requested,
  completed,
}: Readonly<{
  requested: number;
  completed: number;
}>) {
  const percent = requested > 0 ? Math.min(100, Math.round((completed / requested) * 100)) : 0;

  return (
    <div className="grid gap-1">
      <div className="text-2xs text-muted flex justify-between">
        <span>Progress</span>
        <span>{percent}%</span>
      </div>
      <div className="bg-well h-1.5 w-full overflow-hidden rounded-full">
        <div
          className="bg-accent h-full transition-[width] duration-300"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

function ProgressMetrics({ audit }: Readonly<{ audit: Audit }>) {
  const failedColor = audit.failed_count > 0 ? 'text-run-failed text-xl' : 'text-muted text-xl';

  return (
    <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      <div className="border-border-subtle grid gap-1 border-r pr-2 last:border-0 sm:pr-4">
        <Label>Requested</Label>
        <Metric className="text-xl">{audit.requested_count}</Metric>
      </div>
      <div className="border-border-subtle grid gap-1 border-r pr-2 last:border-0 sm:pr-4">
        <Label>Completed</Label>
        <Metric className="text-run-completed text-xl">{audit.completed_count}</Metric>
      </div>
      <div className="border-border-subtle grid gap-1 border-r pr-2 last:border-0 sm:pr-4">
        <Label>Failed</Label>
        <Metric className={failedColor}>{audit.failed_count}</Metric>
      </div>
      <div className="grid gap-1">
        <Label>Created</Label>
        <span className="text-secondary text-sm font-medium">
          {formatDateTime(audit.created_at)}
        </span>
      </div>
    </dl>
  );
}

function ProgressNotices({
  errorMessage,
  cancelNotice,
  onCancelRetry,
  rerunNotice,
  onRerunRetry,
}: Readonly<{
  errorMessage?: string | null;
  cancelNotice?: MutationNoticeData | null;
  onCancelRetry?: () => void;
  rerunNotice?: MutationNoticeData | null;
  onRerunRetry?: () => void;
}>) {
  return (
    <>
      {errorMessage ? <p className="text-danger-text text-sm">{errorMessage}</p> : null}
      {cancelNotice ? <MutationNotice notice={cancelNotice} onRetry={onCancelRetry} /> : null}
      {rerunNotice ? <MutationNotice notice={rerunNotice} onRetry={onRerunRetry} /> : null}
    </>
  );
}

/**
 * Run progress panel (F10, design.md §9.7).
 *
 * Shows the audit's status badge, the requested/completed/failed mono counts,
 * the created + completed timestamps, a Cancel button (enabled only while the
 * backend still accepts a cooperative cancel — i.e. not `reporting`/terminal),
 * and same-origin CSV/MD export links. Progress is driven by
 * the parent's polling of `GET /audits/{id}`; this component is presentational
 * apart from firing the cancel callback.
 */
export function ProgressPanel({
  audit,
  onCancel,
  cancelPending,
  cancelNotice,
  onCancelRetry,
  onRerunFailures,
  rerunPending = false,
  rerunNotice,
  onRerunRetry,
}: Readonly<{
  audit: Audit;
  onCancel: () => void;
  cancelPending: boolean;
  /** The A4 mutation notice for a failed cancel (verbatim 4xx, transient retry). */
  cancelNotice?: MutationNoticeData | null;
  /** Retry affordance for a transient cancel failure. */
  onCancelRetry?: () => void;
  onRerunFailures?: () => void;
  rerunPending?: boolean;
  rerunNotice?: MutationNoticeData | null;
  onRerunRetry?: () => void;
}>) {
  const polling = shouldPollAudit(audit.status);
  const cancelable = isAuditCancelable(audit.status);

  return (
    <Card>
      <CardContent className="grid gap-4 p-[var(--card-padding)]">
        <ProgressHeader
          audit={audit}
          polling={polling}
          cancelable={cancelable}
          cancelPending={cancelPending}
          onCancel={onCancel}
          onRerunFailures={onRerunFailures}
          rerunPending={rerunPending}
        />

        {polling && audit.requested_count > 0 ? (
          <ProgressBar requested={audit.requested_count} completed={audit.completed_count} />
        ) : null}

        <ProgressMetrics audit={audit} />

        <ProgressNotices
          errorMessage={audit.error_message}
          cancelNotice={cancelNotice}
          onCancelRetry={onCancelRetry}
          rerunNotice={rerunNotice}
          onRerunRetry={onRerunRetry}
        />
      </CardContent>
    </Card>
  );
}
