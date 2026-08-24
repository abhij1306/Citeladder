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
  // "Updating…" tracks whether the parent is still polling (not yet terminal);
  // the Cancel button is enabled only while the backend will accept a cancel.
  const polling = shouldPollAudit(audit.status);
  const cancelable = isAuditCancelable(audit.status);

  return (
    <Card>
      <CardContent className="grid gap-5">
        {/* An aggregate over the whole run: it may span several models, so it
            passes `provenance` and never a single representative model. */}
        <MeasurementContext provenance={audit.model_provenance} />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Badge variant="run-status" value={auditBadgeValue(audit.status)}>
              {auditStatusLabel(audit.status)}
            </Badge>
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
          <div className="flex items-center gap-2">
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
              <Button
                variant="secondary"
                size="sm"
                onClick={onRerunFailures}
                disabled={rerunPending}
              >
                {rerunPending ? 'Creating repair…' : 'Rerun failed'}
              </Button>
            ) : null}
          </div>
        </div>

        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div className="grid gap-1">
            <Label>Requested</Label>
            <Metric className="text-lg">{audit.requested_count}</Metric>
          </div>
          <div className="grid gap-1">
            <Label>Completed</Label>
            <Metric className="text-run-completed text-lg">{audit.completed_count}</Metric>
          </div>
          <div className="grid gap-1">
            <Label>Failed</Label>
            <Metric className="text-run-failed text-lg">{audit.failed_count}</Metric>
          </div>
          <div className="grid gap-1">
            <Label>Created</Label>
            <span className="text-secondary text-sm">{formatDateTime(audit.created_at)}</span>
          </div>
        </dl>

        {audit.error_message ? (
          <p className="text-danger-text text-sm">{audit.error_message}</p>
        ) : null}
        {cancelNotice ? <MutationNotice notice={cancelNotice} onRetry={onCancelRetry} /> : null}
        {rerunNotice ? <MutationNotice notice={rerunNotice} onRetry={onRerunRetry} /> : null}
      </CardContent>
    </Card>
  );
}
