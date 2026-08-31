import type { ComponentPropsWithoutRef, ReactNode } from 'react';

import { cn } from '@/lib/utils';

/** Shared editorial structures for authenticated analytical workspaces. */
export function MetricGroup({
  children,
  className,
  ...props
}: Readonly<ComponentPropsWithoutRef<'dl'>>) {
  return (
    <dl
      {...props}
      className={cn(
        'divide-border grid divide-y sm:grid-cols-2 sm:divide-x-0 sm:divide-y-0 sm:[&>*]:border-b sm:[&>*]:border-border sm:[&>*:nth-child(odd)]:border-r sm:[&>*:nth-last-child(-n+2)]:border-b-0 sm:[&>*:nth-last-child(2):nth-child(even)]:border-b lg:grid-flow-col lg:auto-cols-fr lg:[&>*]:border-r lg:[&>*]:border-b-0 lg:[&>*:last-child]:border-r-0',
        className,
      )}
    >
      {children}
    </dl>
  );
}

export function MetricItem({
  label,
  value,
  detail,
  marker,
  className,
}: Readonly<{
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
  marker?: ReactNode;
  className?: string;
}>) {
  return (
    <div
      className={cn(
        'min-w-0 px-0 py-3 sm:px-4 sm:odd:ps-0 sm:even:pe-0 sm:last:pe-0 lg:px-4 lg:odd:ps-4 lg:even:pe-4 lg:first:ps-0 lg:last:pe-0',
        className,
      )}
    >
      <dt className="text-muted flex min-w-0 items-center justify-between gap-2 text-xs font-medium">
        <span className="truncate">{label}</span>
        {marker}
      </dt>
      <dd className="text-foreground mt-2 text-3xl font-medium tracking-[-0.02em] tabular-nums">
        {value}
      </dd>
      {detail ? <dd className="text-muted mt-1 text-xs">{detail}</dd> : null}
    </div>
  );
}

export function EditorialSectionHeader({
  title,
  description,
  actions,
  className,
}: Readonly<{
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}>) {
  return (
    <header className={cn('flex flex-wrap items-end justify-between gap-4', className)}>
      <div className="grid gap-1">
        <h2 className="text-foreground text-lg font-medium">{title}</h2>
        {description ? <p className="text-secondary max-w-[72ch] text-sm">{description}</p> : null}
      </div>
      {actions}
    </header>
  );
}

export function WorkspacePane({
  children,
  selected = false,
  surface = 'open',
  className,
  ...props
}: Readonly<
  ComponentPropsWithoutRef<'section'> & {
    selected?: boolean;
    surface?: 'open' | 'tonal' | 'object';
  }
>) {
  return (
    <section
      {...props}
      className={cn(
        'min-w-0',
        surface === 'tonal' && 'bg-well rounded-[var(--radius-card)]',
        surface === 'object' && 'bg-panel rounded-[var(--radius-card)]',
        selected && 'bg-accent-soft ring-accent-border rounded-[var(--radius-card)] ring-1',
        className,
      )}
    >
      {children}
    </section>
  );
}
