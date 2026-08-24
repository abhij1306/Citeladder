import { ConnectProviderDialog } from '@/components/providers/connect-provider-dialog';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { filterChipClasses } from '@/components/ui/filter-chip-variants';
import { Input, inputClasses } from '@/components/ui/input';
import { MutationNotice } from '@/components/ui/mutation-notice';
import type { MutationNotice as MutationNoticeData } from '@/lib/api/mutation-notice';
import type { LogicalEngine, PromptSet } from '@/lib/api/types';
import { ENGINE_LABELS } from '@/lib/providers/catalog';
import {
  clampRepetitions,
  MAX_REPETITIONS,
  MIN_REPETITIONS,
  toggleEngine,
} from '@/lib/runs/launch';

type Estimate = {
  execution_count: number;
  maximum_attempt_count: number;
  maximum_wall_clock_seconds: number;
  cost_status: string;
  estimated_total_cost_microusd: number | null;
};

export function LaunchDialogView({
  open,
  onOpenChange,
  promptSets,
  promptSetsLoading,
  configuredEngines,
  unverifiedEngines,
  promptSetId,
  setPromptSetId,
  engines,
  setEngines,
  repetitions,
  setRepetitions,
  estimate,
  launchPending,
  launchNotice,
  onLaunch,
  connectOpen,
  setConnectOpen,
  promptSetLocked,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  promptSets: PromptSet[];
  promptSetsLoading: boolean;
  configuredEngines: LogicalEngine[];
  unverifiedEngines: LogicalEngine[];
  promptSetId: string | null;
  setPromptSetId: (id: string) => void;
  engines: LogicalEngine[];
  setEngines: React.Dispatch<React.SetStateAction<LogicalEngine[]>>;
  repetitions: number;
  setRepetitions: React.Dispatch<React.SetStateAction<number>>;
  estimate?: Estimate;
  launchPending: boolean;
  launchNotice: MutationNoticeData | null;
  onLaunch: () => void;
  connectOpen: boolean;
  setConnectOpen: (open: boolean) => void;
  promptSetLocked?: boolean;
}>) {
  const noPromptSets = !promptSetsLoading && !promptSets.length;
  const noEngines = !configuredEngines.length;
  const selected = new Set(engines);
  return (
    <>
      <Dialog
        open={open}
        onOpenChange={onOpenChange}
        title="Launch an audit"
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button onClick={onLaunch} disabled={!promptSetId || !engines.length || launchPending}>
              {launchPending ? 'Launching…' : 'Launch audit'}
            </Button>
          </>
        }
      >
        <div className="grid gap-5">
          {launchNotice ? <MutationNotice notice={launchNotice} onRetry={onLaunch} /> : null}
          <Field label="Prompt set" required>
            {(props) =>
              noPromptSets ? (
                <p className="text-muted text-sm">
                  No prompt set yet. Add prompts on the Prompts screen first.
                </p>
              ) : promptSetLocked ? (
                <p className="text-foreground text-sm font-medium">
                  {promptSets.find((set) => set.id === promptSetId)?.name ??
                    'Commerce Product Visibility'}
                </p>
              ) : (
                <select
                  {...props}
                  className={inputClasses}
                  value={promptSetId ?? ''}
                  onChange={(event) => setPromptSetId(event.target.value)}
                >
                  {promptSets.map((set) => (
                    <option key={set.id} value={set.id}>
                      {set.name}
                      {typeof set.prompt_count === 'number' ? ` (${set.prompt_count})` : ''}
                    </option>
                  ))}
                </select>
              )
            }
          </Field>
          <fieldset className="grid gap-2">
            <legend className="text-secondary text-xs font-medium">
              Engines <span className="text-danger">*</span>
            </legend>
            {noEngines ? (
              <div className="grid gap-2">
                <p className="text-muted text-sm">
                  {unverifiedEngines.length
                    ? `A key is stored for ${unverifiedEngines.map((engine) => ENGINE_LABELS[engine]).join(', ')}, but it has not passed a connection test yet. Test it to launch an audit with it.`
                    : 'No configured engines. Connect a provider to launch an audit.'}
                </p>
                <div>
                  <Button variant="secondary" onClick={() => setConnectOpen(true)}>
                    {unverifiedEngines.length ? 'Test connection' : 'Connect a provider'}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {configuredEngines.map((engine) => (
                  <button
                    key={engine}
                    type="button"
                    role="checkbox"
                    aria-checked={selected.has(engine)}
                    onClick={() => setEngines((current) => toggleEngine(current, engine))}
                    className={filterChipClasses(selected.has(engine))}
                  >
                    {ENGINE_LABELS[engine]}
                  </button>
                ))}
              </div>
            )}
          </fieldset>
          <Field
            label="Repetitions"
            hint={`How many times to run each prompt per engine (${MIN_REPETITIONS}–${MAX_REPETITIONS}).`}
          >
            {(props) => (
              <Input
                {...props}
                type="number"
                min={MIN_REPETITIONS}
                max={MAX_REPETITIONS}
                value={repetitions}
                onChange={(event) => setRepetitions(Number(event.target.value))}
                onBlur={() => setRepetitions((current) => clampRepetitions(current))}
                className="w-28"
              />
            )}
          </Field>
          {estimate ? (
            <div className="border-border-subtle bg-well grid gap-1 rounded-lg border p-3 text-xs">
              <span className="text-foreground font-medium">
                {estimate.execution_count} executions · up to {estimate.maximum_attempt_count}{' '}
                attempts
              </span>
              <span className="text-muted">
                Maximum wall-clock budget {estimate.maximum_wall_clock_seconds}s · cost{' '}
                {estimate.cost_status}
                {estimate.estimated_total_cost_microusd !== null
                  ? ` · ~$${(estimate.estimated_total_cost_microusd / 1_000_000).toFixed(4)}`
                  : ' · unavailable'}
              </span>
            </div>
          ) : null}
        </div>
      </Dialog>
      <ConnectProviderDialog open={connectOpen} onOpenChange={setConnectOpen} />
    </>
  );
}
