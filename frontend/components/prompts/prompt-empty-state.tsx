'use client';

import { MessageSquarePlus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';

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
    <EmptyState
      icon={MessageSquarePlus}
      heading="No prompts yet"
      description="Add the questions you want to track across AI engines."
      action={
        <>
          <Button onClick={onAdd}>Add prompt</Button>
          <Button variant="secondary" onClick={onImport}>
            Import CSV
          </Button>
        </>
      }
    />
  );
}
