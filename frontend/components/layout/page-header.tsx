'use client';

import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

import { eyebrowClasses } from '@/components/ui/eyebrow';
import { displayHeadingXlClasses } from '@/components/ui/typography';

import { resolveTitle } from './page-titles';

/**
 * PageHeader — the page's accessible label plus its optional description and
 * actions row, rendered as the first row of the content column.
 *
 * The route-derived title is deliberately NOT painted. The sidebar's active
 * item already names the current destination, so repeating it as a 22px
 * heading spent the most valuable strip of the page restating what the user
 * just clicked — the reference dashboards (Peec, Searchable) put filters and
 * content there instead, and read far calmer for it.
 *
 * It still renders as an `sr-only` `<h1>`, because dropping the heading
 * outright would leave every authed route without a top-level heading: screen
 * readers lose the "what page am I on" landmark and the document outline
 * starts at `<h2>`. Invisible to sighted users, unchanged for assistive tech.
 *
 * A page whose title is real CONTENT rather than a route name (a crawled URL,
 * a product) still renders its own visible `<h1>` — see url-detail.tsx. That is
 * information, not chrome, so it is not what this component suppresses.
 *
 * When a page passes neither `summary` nor `actions` the component collapses to
 * just that `sr-only` heading, contributing no box and no grid gap.
 *
 * Set `showTitle` to render the visible heading anyway — for a route where the
 * title carries information the sidebar does not.
 */
export function PageHeader({
  summary,
  actions,
  title,
  eyebrow,
  showTitle = false,
  className,
}: Readonly<{
  summary?: ReactNode;
  actions?: ReactNode;
  /** Overrides the route-derived title (rare — prefer the table above). */
  title?: string;
  /** Optional overline above the title (ADS breadcrumb-row stand-in). */
  eyebrow?: ReactNode;
  /** Paints the title visibly. Off by default — the sidebar already names it. */
  showTitle?: boolean;
  className?: string;
}>) {
  const pathname = usePathname() ?? '';
  const resolved = title ?? resolveTitle(pathname);

  const heading = (
    <h1
      className={cn(
        showTitle
          ? cn(displayHeadingXlClasses, 'min-w-0 flex-1 [overflow-wrap:break-word]')
          : 'sr-only',
      )}
    >
      {resolved}
    </h1>
  );

  // Nothing visible to lay out — emit the bare landmark so the grid gets no row.
  if (!showTitle && !summary && !actions && !eyebrow) return heading;

  return (
    <div className={cn('flex flex-col gap-1 pb-1', className)}>
      {eyebrow ? <p className={eyebrowClasses}>{eyebrow}</p> : null}
      <div className="flex flex-nowrap items-start gap-2">
        {heading}
        {actions ? (
          <div className="ms-auto flex shrink-0 items-center gap-2 ps-8">{actions}</div>
        ) : null}
      </div>
      {summary ? (
        <p className="text-muted max-w-[70ch] text-sm leading-relaxed">{summary}</p>
      ) : null}
    </div>
  );
}
