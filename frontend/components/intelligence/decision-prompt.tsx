'use client';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';

/**
 * DecisionPrompt — the ONLY blocking UI in the product.
 *
 * §1 allows exactly two decisions: saving content, and running or scheduling
 * an audit. The `kind` union is closed to those two on purpose — adding a
 * third member is the signal that a design has grown a gate it should not
 * have, and the plan is explicit that the fix is to go back to the layer plan
 * rather than add one here.
 *
 * The prompt states precisely what will be spent or written. A confirmation
 * that says "Are you sure?" is not one; the user cannot weigh a cost they
 * were not shown.
 */
export type DecisionKind = 'save-content' | 'run-audit';

/** Static: only one DecisionPrompt is open at a time (it is a modal). */
const BLOCKERS_ID = 'decision-prompt-blockers';

const DECISION_COPY: Record<
  DecisionKind,
  { title: string; confirmLabel: string; declineLabel: string }
> = {
  'save-content': { title: 'Save this content?', confirmLabel: 'Save', declineLabel: "Don't save" },
  'run-audit': { title: 'Run this audit?', confirmLabel: 'Run audit', declineLabel: "Don't run" },
};

/**
 * One blocking validation failure. Carries its own ID because two rules can
 * produce the same message — keying the list by message text would collide and
 * silently drop a row, and keying by index would reorder wrongly when the
 * validation set changes between renders.
 */
export type DecisionBlocker = {
  /** Stable identity, e.g. the failing rule or claim ID. */
  id: string;
  /** What is wrong, in the user's terms. */
  message: string;
};

export type DecisionPromptProps = {
  kind: DecisionKind;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  /** Records an explicit negative decision; closing the dialog does not. */
  onDecline?: () => void;
  /**
   * Exactly what will be spent or written — "3 pages, ~12k tokens on your
   * OpenAI key" or "Writes revision 4 of /pricing". Required: a decision
   * prompt with no stated consequence is a nag, not a decision.
   */
  consequence: string;
  /**
   * Blocking validation failures. When present, confirmation is disabled —
   * §7.3 requires blocking flags to disable save at the UI *and* the API.
   */
  blockers?: readonly DecisionBlocker[];
  /** In-flight state for the confirm action. */
  pending?: boolean;
  /** Recoverable request failure; does not disable retry. */
  error?: string;
};

export function DecisionPrompt({
  kind,
  open,
  onOpenChange,
  onConfirm,
  onDecline,
  consequence,
  blockers = [],
  pending = false,
  error,
}: Readonly<DecisionPromptProps>) {
  const { title, confirmLabel, declineLabel } = DECISION_COPY[kind];
  const isBlocked = blockers.length > 0;

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          {onDecline ? (
            <Button variant="secondary" onClick={onDecline} disabled={pending}>
              {declineLabel}
            </Button>
          ) : null}
          <Button
            onClick={onConfirm}
            disabled={isBlocked || pending}
            // A disabled button leaves the tab order, so without this the
            // reason it is disabled is only discoverable by browsing the body.
            aria-describedby={isBlocked ? BLOCKERS_ID : undefined}
          >
            {pending ? 'Working…' : confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4 py-3">
        <div className="flex flex-col gap-1">
          <p className="text-subtle text-2xs font-medium tracking-wide uppercase">What this does</p>
          <p className="text-foreground text-sm leading-relaxed">{consequence}</p>
        </div>

        {isBlocked ? (
          <div
            id={BLOCKERS_ID}
            className="border-danger bg-danger-bg flex flex-col gap-2 rounded-md border p-3"
          >
            <p className="text-danger-text text-xs font-semibold">
              {blockers.length === 1
                ? 'One issue blocks this'
                : `${blockers.length} issues block this`}
            </p>
            <ul className="flex flex-col gap-1">
              {blockers.map((blocker) => (
                <li key={blocker.id} className="text-danger-text text-xs leading-relaxed">
                  {blocker.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {error ? (
          <p
            role="alert"
            className="border-danger bg-danger-bg text-danger-text rounded-md border p-3 text-xs"
          >
            {error}
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}
