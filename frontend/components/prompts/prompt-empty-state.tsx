'use client';

import { MessageSquarePlus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import { IconChip } from '@/components/ui/icon-chip';
import { displayHeadingXlClasses } from '@/components/ui/typography';

/**
 * Empty state (F7) — shown when the active project's prompt set has no prompts.
 * Midnight empty-state pattern: mono eyebrow + display heading + ghost CTAs
 * inviting the first manual prompt or a CSV import.
 */
export function PromptEmptyState({
  onAdd,
  onImport,
}: Readonly<{ onAdd: () => void; onImport: () => void }>) {
  return (
    <div className="bg-panel shadow-card flex flex-col items-center justify-center gap-4 rounded-lg px-[var(--card-padding)] py-[var(--empty-state-padding)] text-center">
      <IconChip>
        <MessageSquarePlus className="size-6" aria-hidden />
      </IconChip>
      <div className="grid max-w-sm gap-1">
        <p className={eyebrowClasses}>Prompt library</p>
        <h3 className={displayHeadingXlClasses}>No prompts yet</h3>
        {/* One line: the "enter them one at a time or import a CSV" half just
            read the two buttons back to the user. */}
        <p className="text-secondary mt-1 text-sm">
          Add the questions you want to track across AI engines.
        </p>
      </div>
      {/* Two equal paths, so the first is primary and the second secondary —
          both ghost gave the screen no obvious action. */}
      <div className="flex gap-2">
        <Button onClick={onAdd}>Add prompt</Button>
        <Button variant="secondary" onClick={onImport}>
          Import CSV
        </Button>
      </div>
    </div>
  );
}
