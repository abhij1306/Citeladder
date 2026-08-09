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
import type { ProductEngineFilter } from '@/lib/products/catalog';
import { ENGINE_ORDER, engineLabel } from '@/lib/providers/catalog';

/**
 * Engine slice filter shared by the products surfaces (visibility tab +
 * evidence drill-down): 'all' (cross-engine) plus one item per logical
 * engine. Controlled view — the parent owns the filter state.
 */
export function EngineFilterDropdown({
  engine,
  onChange,
}: Readonly<{
  engine: ProductEngineFilter;
  onChange: (engine: ProductEngineFilter) => void;
}>) {
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <Button variant="secondary" size="sm" aria-label="Filter by engine">
          <span className="text-muted">Engine:</span>
          <span className="font-medium">
            {engine === 'all' ? 'All engines' : engineLabel(engine)}
          </span>
          <ChevronDown className="text-muted size-3" aria-hidden />
        </Button>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownLabel>Engine</DropdownLabel>
        <DropdownRadioGroup value={engine}>
          <DropdownRadioItem value="all" onSelect={() => onChange('all')}>
            All engines
          </DropdownRadioItem>
          {ENGINE_ORDER.map((option) => (
            <DropdownRadioItem key={option} value={option} onSelect={() => onChange(option)}>
              {engineLabel(option)}
            </DropdownRadioItem>
          ))}
        </DropdownRadioGroup>
      </DropdownContent>
    </Dropdown>
  );
}
