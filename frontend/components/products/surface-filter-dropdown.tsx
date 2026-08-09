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
import { MEASUREMENT_SURFACE_LABEL } from '@/lib/products/catalog';

/** Display label for one analysis surface id (`''` = measurement). */
function surfaceLabel(surface: string): string {
  return surface === '' ? MEASUREMENT_SURFACE_LABEL : surface;
}

/**
 * Surface slice filter for the Commerce Visibility workspace: the
 * measurement surface (`''`, labelled "Answer-engine APIs") plus every
 * configured surface id from the projection's `available_surfaces`,
 * verbatim. There is deliberately NO "All surfaces" option — omission is
 * the measurement slice, not an aggregate. Controlled view — the parent
 * owns the filter state.
 */
export function SurfaceFilterDropdown({
  surfaces,
  surface,
  onChange,
}: Readonly<{
  /** `available_surfaces` from the projection (includes `''`). */
  surfaces: readonly string[];
  surface: string;
  onChange: (surface: string) => void;
}>) {
  const options = surfaces.length > 0 ? surfaces : [''];
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <Button variant="secondary" size="sm" aria-label="Filter by surface">
          <span className="text-muted">Surface:</span>
          <span className="font-medium">{surfaceLabel(surface)}</span>
          <ChevronDown className="text-muted size-3" aria-hidden />
        </Button>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownLabel>Surface</DropdownLabel>
        <DropdownRadioGroup value={surface}>
          {options.map((option) => (
            <DropdownRadioItem
              key={option === '' ? '__measurement__' : option}
              value={option}
              onSelect={() => onChange(option)}
            >
              {surfaceLabel(option)}
            </DropdownRadioItem>
          ))}
        </DropdownRadioGroup>
      </DropdownContent>
    </Dropdown>
  );
}
