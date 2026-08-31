import type { HTMLAttributes, ReactNode, Ref, TdHTMLAttributes, ThHTMLAttributes } from 'react';

import { cn } from '@/lib/utils';

/**
 * Dense analytics table — the shared semantic ledger treatment:
 *  - sticky header (--table-header-height) on bg-panel, ruled top and with
 *    a 2px under-rule (border-b-2); no vertical column-separator
 *    hairlines, which made the tables read as
 *    spreadsheets rather than designed surfaces
 *  - --table-row-height rows, --text-sm cells, subtle ROW hairlines only
 *  - everything left-aligned (including numeric columns — the mock aligns the
 *    column edge, not the digits); `numeric` still applies tabular numerals
 *  - hover tints the row with background-alt; `highlight` marks the user's
 *    own row with the same tint permanently
 * The wrapper is scroll-capable so the sticky header pins on vertical scroll.
 *
 * The header label recipe (`tableHeadClasses`) is deliberately NOT the shared
 * `eyebrowClasses` micro-label: it uses the product table-header composite
 * (12/16, medium, text-secondary, sentence case), and keeping the strings separate
 * stops a future eyebrow change from silently restyling every table.
 */
const tableHeadClasses = 'text-xs text-secondary font-medium whitespace-nowrap';
export function Table({
  children,
  className,
  wrapperClassName,
  wrapperRef,
}: Readonly<{
  children: ReactNode;
  className?: string;
  wrapperClassName?: string;
  wrapperRef?: Ref<HTMLDivElement>;
}>) {
  return (
    <div ref={wrapperRef} className={cn('relative w-full overflow-auto', wrapperClassName)}>
      <table className={cn('w-full border-collapse text-sm', className)}>{children}</table>
    </div>
  );
}

export function TableHeader({
  children,
  className,
  ...props
}: Readonly<HTMLAttributes<HTMLTableSectionElement>>) {
  return (
    <thead {...props} className={cn(className)}>
      {children}
    </thead>
  );
}

export function TableBody({
  children,
  className,
  ...props
}: Readonly<HTMLAttributes<HTMLTableSectionElement>>) {
  return (
    <tbody {...props} className={cn(className)}>
      {children}
    </tbody>
  );
}

export function TableRow({
  children,
  className,
  highlight,
  ...props
}: Readonly<HTMLAttributes<HTMLTableRowElement> & { highlight?: boolean }>) {
  return (
    <tr
      {...props}
      className={cn(
        'hover:bg-background-alt h-[var(--table-row-height)] transition-colors',
        highlight && 'bg-background-alt',
        className,
      )}
    >
      {children}
    </tr>
  );
}

export function TableHead({
  children,
  className,
  numeric,
  ...props
}: Readonly<ThHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }>) {
  return (
    <th
      {...props}
      className={cn(
        tableHeadClasses,
        'border-border-subtle bg-panel sticky top-0 z-10 h-[var(--table-header-height)] border-t border-b-2 px-[var(--table-cell-padding-x)] text-left align-middle',
        numeric && 'tabular-nums',
        className,
      )}
    >
      {children}
    </th>
  );
}

export function TableCell({
  children,
  className,
  numeric,
  ...props
}: Readonly<TdHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }>) {
  return (
    <td
      {...props}
      className={cn(
        'text-foreground border-border-subtle px-[var(--table-cell-padding-x)] py-[var(--table-cell-padding-y)] text-left align-middle text-sm',
        // Row rule, dropped on the last row.
        'border-b [tr:last-child>&]:border-b-0',
        numeric && 'tabular-nums',
        className,
      )}
    >
      {children}
    </td>
  );
}

/** Numeric table cell that becomes a labelled key/value row below `md`. */
export function TableRecordMetricCell({
  children,
  className,
  label,
  ...props
}: Readonly<Omit<TdHTMLAttributes<HTMLTableCellElement>, 'data-label'> & { label: string }>) {
  return (
    <TableCell
      {...props}
      numeric
      data-label={label}
      className={cn(
        'grid grid-cols-[1fr_auto] gap-3 border-b-0 px-4 py-1 before:text-xs before:text-muted before:content-[attr(data-label)]',
        'md:table-cell md:border-b md:px-[var(--table-cell-padding-x)] md:py-[var(--table-cell-padding-y)] md:before:hidden',
        className,
      )}
    >
      {children}
    </TableCell>
  );
}
