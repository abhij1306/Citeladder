'use client';

import {
  AE,
  AR,
  AT,
  AU,
  BE,
  BR,
  CA,
  CH,
  CL,
  CO,
  DE,
  DK,
  ES,
  FI,
  FR,
  GB,
  IE,
  IL,
  IN,
  IT,
  JP,
  KR,
  MX,
  NL,
  NO,
  NZ,
  PL,
  PT,
  SE,
  SG,
  US,
  ZA,
} from 'country-flag-icons/react/3x2';
import { useId, useRef, useState } from 'react';

import { Input } from '@/components/ui/input';
import { menuItemVariants, menuPanelClasses } from '@/components/ui/menu-variants';
import type { MarketOption } from '@/lib/setup/markets';
import { cn } from '@/lib/utils';

const COUNTRY_FLAGS = {
  AE,
  AR,
  AT,
  AU,
  BE,
  BR,
  CA,
  CH,
  CL,
  CO,
  DE,
  DK,
  ES,
  FI,
  FR,
  GB,
  IE,
  IL,
  IN,
  IT,
  JP,
  KR,
  MX,
  NL,
  NO,
  NZ,
  PL,
  PT,
  SE,
  SG,
  US,
  ZA,
} as const;

/**
 * MarketSelect (F6) — a lightweight searchable select (combobox) for the
 * guided setup's Market step: an Input whose focus/typing opens a filtered
 * option list. Click or ArrowUp/ArrowDown + Enter to pick; blur commits a
 * typed text that exactly matches an option and otherwise reverts to the
 * selected label; Escape always reverts.
 *
 * Built on the standard Input + dropdown tokens (bg-elevated,
 * shadow-elevated) rather than the Radix menu so typing focus never leaves
 * the input. Selection is committed via `onChange(value)`; the raw text is
 * component-local, so react-hook-form only ever sees valid option values.
 */
export function MarketSelect({
  id,
  ariaLabel,
  value,
  onChange,
  onBlur,
  options,
  placeholder,
  showCountryFlags = false,
  'aria-describedby': ariaDescribedBy,
  'aria-invalid': ariaInvalid,
  'aria-required': ariaRequired,
}: Readonly<{
  id?: string;
  ariaLabel: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  options: readonly MarketOption[];
  placeholder?: string;
  showCountryFlags?: boolean;
  'aria-describedby'?: string;
  'aria-invalid'?: boolean;
  'aria-required'?: boolean;
}>) {
  const listId = useId();
  const containerRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  // `query` is null when the input shows the committed selection's label.
  const [query, setQuery] = useState<string | null>(null);
  const [highlight, setHighlight] = useState(0);

  const selected = options.find((option) => option.value === value);
  // Off-list stored values (a project saved with a market outside the curated
  // list) still render their raw code rather than a misleading blank field.
  const text = query ?? selected?.label ?? value;
  const needle = (query ?? '').trim().toLowerCase();
  const filtered = needle
    ? options.filter(
        (option) =>
          option.label.toLowerCase().includes(needle) ||
          option.value.toLowerCase().includes(needle),
      )
    : options;
  const showList = open && filtered.length > 0;

  const commit = (option: MarketOption) => {
    onChange(option.value);
    setQuery(null);
    setOpen(false);
  };

  /**
   * Close the list and settle the text.
   *
   * `blurred` marks the real blur path. Escape closes the list but leaves focus
   * in the input, so it must NOT fire `onBlur` — react-hook-form would mark the
   * field touched (and validate it) while the user is still typing in it.
   */
  const close = ({ blurred = false }: { blurred?: boolean } = {}) => {
    // On blur, a typed text that exactly matches an option (label or code) is
    // a completed selection — commit it rather than silently discarding it.
    // Escape never commits; it always reverts.
    if (blurred && query !== null) {
      const q = query.trim().toLowerCase();
      const exact = options.find(
        (option) => option.label.toLowerCase() === q || option.value.toLowerCase() === q,
      );
      if (exact) {
        commit(exact);
        onBlur?.();
        return;
      }
    }
    setOpen(false);
    setQuery(null);
    if (blurred) onBlur?.();
  };

  return (
    <div ref={containerRef} className="relative">
      {showCountryFlags && selected ? (
        <CountryFlag
          code={selected.value}
          className="pointer-events-none absolute top-1/2 left-3 z-1 -translate-y-1/2"
        />
      ) : null}
      <Input
        id={id}
        // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- This is the semantic input in an editable ARIA combobox; a native select is not editable.
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList ? `${listId}-${filtered[highlight]?.value}` : undefined}
        aria-label={ariaLabel}
        aria-describedby={ariaDescribedBy}
        aria-invalid={ariaInvalid}
        aria-required={ariaRequired}
        autoComplete="off"
        placeholder={placeholder}
        value={text}
        className={showCountryFlags ? 'pl-10' : undefined}
        onFocus={() => {
          setOpen(true);
          setQuery('');
          setHighlight(0);
        }}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
          setHighlight(0);
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown') {
            event.preventDefault();
            setOpen(true);
            setHighlight((current) => Math.min(current + 1, filtered.length - 1));
          } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            setHighlight((current) => Math.max(current - 1, 0));
          } else if (event.key === 'Enter') {
            event.preventDefault();
            const option = filtered[highlight] ?? filtered[0];
            if (open && option) commit(option);
          } else if (event.key === 'Escape') {
            close();
          }
        }}
        onBlur={() => {
          // Defer so an option mousedown (which preventDefaults and keeps
          // focus) wins over the close.
          setTimeout(() => {
            if (!containerRef.current?.contains(document.activeElement)) {
              close({ blurred: true });
            }
          }, 0);
        }}
      />
      {showList ? (
        <ul
          id={listId}
          // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role, jsx-a11y/no-noninteractive-element-to-interactive-role -- Editable combobox popup; native select/datalist cannot preserve the active-descendant interaction.
          role="listbox"
          aria-label={ariaLabel}
          data-open="true"
          className={cn(menuPanelClasses, 'absolute mt-1 max-h-56 w-full overflow-auto')}
        >
          {filtered.map((option, index) => (
            <li
              key={option.value}
              id={`${listId}-${option.value}`}
              // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role, jsx-a11y/no-noninteractive-element-to-interactive-role -- ARIA listbox options keep focus on the editable input.
              role="option"
              aria-selected={option.value === value}
              onMouseDown={(event) => {
                event.preventDefault();
                commit(option);
              }}
              onMouseEnter={() => setHighlight(index)}
              className={cn(
                menuItemVariants({ selected: option.value === value }),
                'grid gap-3 text-xs leading-5',
                showCountryFlags
                  ? 'grid-cols-[1.25rem_minmax(0,1fr)_auto]'
                  : 'grid-cols-[minmax(0,1fr)_auto]',
                index === highlight && option.value !== value && 'bg-background-alt',
              )}
            >
              {showCountryFlags ? <CountryFlag code={option.value} /> : null}
              <span className="min-w-0 truncate">{option.label}</span>
              {option.value.trim().toLowerCase() !== option.label.trim().toLowerCase() ? (
                <span className="mono text-muted max-w-24 truncate text-xs">{option.value}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function CountryFlag({ code, className }: Readonly<{ code: string; className?: string }>) {
  if (code === 'GLOBAL') {
    return (
      <span
        data-country-flag="GLOBAL"
        className={cn(
          'flex size-5 shrink-0 items-center justify-center text-base leading-none',
          className,
        )}
        aria-hidden
      >
        🌐
      </span>
    );
  }
  const Flag = COUNTRY_FLAGS[code as keyof typeof COUNTRY_FLAGS];
  return Flag ? (
    <Flag
      data-country-flag={code}
      className={cn('h-3.5 w-5 shrink-0 overflow-hidden rounded-[2px]', className)}
      aria-hidden
    />
  ) : null;
}
