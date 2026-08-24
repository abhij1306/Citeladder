'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { inputClasses } from '@/components/ui/input';
import { MutationNotice } from '@/components/ui/mutation-notice';
import { queryKeys } from '@/lib/api/query-keys';
import { runsApi } from '@/lib/api/runs';
import type { AuditScheduleCadence, LogicalEngine, PromptSet } from '@/lib/api/types';
import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import { formatUtcTimestamp } from '@/lib/format';

const CADENCE_LABELS: Record<AuditScheduleCadence, string> = {
  one_time: 'One time',
  every_n_minutes: 'Every N minutes',
  hourly: 'Hourly',
  daily: 'Daily',
  weekly: 'Weekly',
};

/** Compact schedule ledger: schedules use the same frozen prompt set and engines as a run. */
export function AuditSchedules({
  projectId,
  promptSets,
}: Readonly<{ projectId: string; promptSets: PromptSet[] }>) {
  const queryClient = useQueryClient();
  const [promptSetId, setPromptSetId] = useState(promptSets[0]?.id ?? '');
  const [cadence, setCadence] = useState<AuditScheduleCadence>('weekly');
  const [intervalMinutes, setIntervalMinutes] = useState('60');
  const [engines, setEngines] = useState<LogicalEngine[]>(['chatgpt']);
  const schedulesQuery = useQuery({
    queryKey: queryKeys.runs.schedules(projectId),
    queryFn: ({ signal }) => runsApi.listSchedules(projectId, { signal }),
  });
  const createMutation = useMutation({
    mutationFn: () =>
      runsApi.createSchedule(projectId, {
        prompt_set_id: promptSetId,
        cadence,
        interval_minutes: cadence === 'every_n_minutes' ? Number(intervalMinutes) : undefined,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
        engines,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs.schedules(projectId) });
    },
  });
  const canCreate = Boolean(promptSetId) && engines.length > 0 && !createMutation.isPending;

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle>Scheduled audits</CardTitle>
          <p className="text-muted mt-1 text-xs">
            Runs use the selected prompt set and your connected engines.
          </p>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4">
        {schedulesQuery.isError ? (
          <Alert tone="danger">Could not load scheduled audits.</Alert>
        ) : null}
        {schedulesQuery.data?.length ? (
          <ul className="border-border-subtle divide-border-subtle divide-y rounded-lg border">
            {schedulesQuery.data.map((schedule) => (
              <li
                key={schedule.id}
                className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
              >
                <span className="text-foreground font-medium">
                  {CADENCE_LABELS[schedule.cadence]}
                </span>
                <span className="text-secondary">
                  {schedule.engines.join(', ')} · next{' '}
                  {schedule.next_run_at ? formatUtcTimestamp(schedule.next_run_at) : '—'}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        {!schedulesQuery.data?.length && !schedulesQuery.isLoading ? (
          <p className="text-muted text-sm">No scheduled audits yet.</p>
        ) : null}
        {promptSets.length === 0 ? (
          <Alert tone="info">Add prompts before scheduling an audit.</Alert>
        ) : (
          <div className="grid gap-3 border-t pt-4 sm:grid-cols-3">
            <label className="text-secondary grid gap-1 text-xs font-medium">
              <span>Prompt set</span>
              <select
                className={inputClasses}
                value={promptSetId}
                onChange={(event) => setPromptSetId(event.target.value)}
              >
                {promptSets.map((set) => (
                  <option key={set.id} value={set.id}>
                    {set.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-secondary grid gap-1 text-xs font-medium">
              <span>Cadence</span>
              <select
                className={inputClasses}
                value={cadence}
                onChange={(event) => setCadence(event.target.value as AuditScheduleCadence)}
              >
                {Object.entries(CADENCE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {cadence === 'every_n_minutes' ? (
              <label className="text-secondary grid gap-1 text-xs font-medium">
                <span>Minutes</span>
                <input
                  className={inputClasses}
                  min="5"
                  type="number"
                  value={intervalMinutes}
                  onChange={(event) => setIntervalMinutes(event.target.value)}
                />
              </label>
            ) : null}
            <fieldset className="sm:col-span-2">
              <legend className="text-secondary mb-1 text-xs font-medium">Engines</legend>
              <div className="flex flex-wrap gap-2">
                {(['chatgpt', 'gemini', 'claude'] as const).map((engine) => (
                  <label key={engine} className="text-secondary flex items-center gap-1.5 text-sm">
                    <input
                      type="checkbox"
                      checked={engines.includes(engine)}
                      onChange={() =>
                        setEngines((current) =>
                          current.includes(engine)
                            ? current.filter((value) => value !== engine)
                            : [...current, engine],
                        )
                      }
                    />
                    {engine}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="flex items-end">
              <Button onClick={() => createMutation.mutate()} disabled={!canCreate}>
                {createMutation.isPending ? 'Scheduling…' : 'Schedule audit'}
              </Button>
            </div>
          </div>
        )}
        {createMutation.isError ? (
          <MutationNotice
            notice={mutationNoticeForError(createMutation.error, { action: 'schedule the audit' })}
            onRetry={() => createMutation.mutate()}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}
