'use client';

import { ChevronDown } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dropdown,
  DropdownContent,
  DropdownLabel,
  DropdownRadioGroup,
  DropdownRadioItem,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import type { useProductVisibilityQueries } from '@/lib/products/use-products-screen';

type VisibilityQueries = ReturnType<typeof useProductVisibilityQueries>;

export function RunSelectorDropdown({
  runOptions,
  activeRunId,
  selectRun,
}: Readonly<{
  runOptions: VisibilityQueries['runOptions'];
  activeRunId: string | null;
  selectRun: (id: string | null) => void;
}>) {
  const activeRun = runOptions.find((run) => run.id === activeRunId) ?? null;
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <Button variant="secondary" size="sm" aria-label="Select run">
          <span className="text-muted">Run:</span>
          <span className="font-medium">{activeRun?.label ?? 'Latest'}</span>
          <ChevronDown className="text-muted size-3" aria-hidden />
        </Button>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownLabel>Runs</DropdownLabel>
        <DropdownRadioGroup value={activeRunId ?? '__latest__'}>
          <DropdownRadioItem value="__latest__" onSelect={() => selectRun(null)}>
            Latest
          </DropdownRadioItem>
          {runOptions.map((run) => (
            <DropdownRadioItem key={run.id} value={run.id} onSelect={() => selectRun(run.id)}>
              {run.label}
            </DropdownRadioItem>
          ))}
        </DropdownRadioGroup>
      </DropdownContent>
    </Dropdown>
  );
}
