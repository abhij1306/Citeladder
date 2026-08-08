'use client';

import { useId, useState } from 'react';
import { Check, Pencil, Undo2, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

import { EvidenceLink, type EvidenceRef } from './evidence-link';

/**
 * EditableFact — inline correction, replacing every approval card.
 *
 * The model (frontend-growth-intelligence.md §1): where a derived fact is
 * wrong the user edits it in place, wherever it is displayed. A correction is
 * durable, attributable, and withdrawable. There is no separate surface for
 * blessing facts that are already right, so this component has no "approve"
 * affordance — only edit and withdraw.
 *
 * Withdrawing restores the derived value rather than clearing the field: the
 * derived value never stops existing, it is only overridden.
 */
export type Correction = {
  value: string;
  /** Who made the correction — corrections are attributable. */
  author: string;
  /** When, as display text. */
  correctedAt: string;
};

export type EditableFactProps = {
  /** Field name, e.g. "Founded". */
  label: string;
  /** The value the system derived. Always retained, even when overridden. */
  derivedValue: string;
  /** The active correction, when one exists. */
  correction?: Correction | null;
  /** Where the derived value came from. */
  evidence?: EvidenceRef | null;
  /** Persist a correction. Errors surface to the caller's mutation state. */
  onCorrect: (value: string) => void;
  /** Withdraw the correction, restoring the derived value. */
  onWithdraw: () => void;
  /**
   * Disables every affordance — insufficient permission, or a save in flight.
   *
   * Set this while `onCorrect` is pending: the editor deliberately stays open
   * across the mutation so a rejected save keeps the user's draft, and this is
   * what stops a second submit landing during the first.
   */
  disabled?: boolean;
  className?: string;
};

export function EditableFact({
  label,
  derivedValue,
  correction,
  evidence,
  onCorrect,
  onWithdraw,
  disabled = false,
  className,
}: Readonly<EditableFactProps>) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState('');
  /** The value handed to `onCorrect`, pending confirmation from the caller. */
  const [submitted, setSubmitted] = useState<string | null>(null);
  const inputId = useId();

  const displayValue = correction ? correction.value : derivedValue;

  // A submitted value that shows up as the active correction is the signal the
  // mutation landed, so the editor closes. Derived during render rather than in
  // an effect: this is a function of props, not a side effect. Keyed on the
  // SUBMITTED value, not the draft — the draft is seeded from the current
  // correction when the editor opens, which would close it immediately. A
  // rejected save leaves `correction` unchanged, so the editor stays open with
  // the draft intact.
  const landed = submitted !== null && correction?.value === submitted;
  const editorOpen = isEditing && !landed;

  const startEditing = () => {
    setDraft(displayValue);
    setSubmitted(null);
    setIsEditing(true);
  };

  const cancel = () => {
    setSubmitted(null);
    setIsEditing(false);
  };

  const submit = () => {
    if (disabled) return;

    const trimmed = draft.trim();

    // Clearing the field, or retyping the derived value, both mean "remove the
    // override" — so when a correction is active they withdraw it rather than
    // discarding the edit silently.
    if (trimmed.length === 0 || trimmed === derivedValue) {
      setIsEditing(false);
      if (correction) onWithdraw();
      return;
    }

    // Re-submitting the value already stored is a no-op, not a mutation.
    if (trimmed === correction?.value) {
      setIsEditing(false);
      return;
    }

    // The editor stays OPEN across the mutation. `disabled` is how the caller
    // reports an in-flight save, and closing here would discard the user's
    // draft if that save is then rejected — `draft` is only re-seeded from
    // `displayValue`, which still holds the pre-save value. The caller closes
    // the editor by clearing `disabled` once the correction has landed.
    setSubmitted(trimmed);
    onCorrect(trimmed);
  };

  if (editorOpen) {
    return (
      <div className={cn('flex flex-col gap-2', className)}>
        <label
          htmlFor={inputId}
          className="text-subtle text-2xs font-medium tracking-wide uppercase"
        >
          {label}
        </label>
        <div className="flex items-center gap-2">
          <Input
            id={inputId}
            value={draft}
            autoFocus
            // `disabled` can flip to true while the editor is already open (an
            // in-flight save), so the editing branch honours it too — otherwise
            // Enter fires a second mutation during the first.
            disabled={disabled}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (disabled) return;
              if (event.key === 'Enter') submit();
              if (event.key === 'Escape') cancel();
            }}
          />
          <Button
            type="button"
            size="sm"
            disabled={disabled}
            onClick={submit}
            aria-label={`Save correction to ${label}`}
          >
            <Check aria-hidden className="size-4" />
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={disabled}
            onClick={cancel}
            aria-label="Cancel"
          >
            <X aria-hidden className="size-4" />
          </Button>
        </div>
        {/* The derived value stays visible while correcting, so the user can
            see exactly what they are overriding. */}
        <p className="text-subtle text-2xs">Derived value: {derivedValue}</p>
      </div>
    );
  }

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <p className="text-subtle text-2xs font-medium tracking-wide uppercase">{label}</p>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-foreground text-sm">{displayValue}</span>

        {correction ? (
          <span className="bg-info-bg text-info-text text-2xs rounded-sm px-1 py-0.5 font-medium">
            Corrected
          </span>
        ) : null}

        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={disabled}
          onClick={startEditing}
          aria-label={`Correct ${label}`}
        >
          <Pencil aria-hidden className="size-3.5" />
        </Button>

        {correction ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={disabled}
            onClick={onWithdraw}
            aria-label={`Withdraw correction to ${label}`}
          >
            <Undo2 aria-hidden className="size-3.5" />
            Withdraw
          </Button>
        ) : null}
      </div>

      {/* Attribution — a correction that cannot be traced to a person is not
          attributable, which is half of what makes it trustworthy. */}
      {correction ? (
        <p className="text-subtle text-2xs">
          Corrected by {correction.author} · {correction.correctedAt} · derived value was{' '}
          {derivedValue}
        </p>
      ) : null}

      {evidence ? <EvidenceLink evidence={evidence} /> : null}
    </div>
  );
}
