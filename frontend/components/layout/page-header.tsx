'use client';

import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

import { eyebrowClasses } from '@/components/ui/eyebrow';
import { displayHeadingXlClasses } from '@/components/ui/typography';

import { resolveTitle } from './page-titles';

/**
 * PageHeader — the page's accessible label plus its optional description and
 * actions row. The app shell places this owner in the top bar.
 *
 * Route titles stay visible so every workspace has a stable orientation point.
 */
export function PageHeader({
  summary,
  actions,
  title,
  eyebrow,
  showTitle,
  className,
}: Readonly<{
  summary?: ReactNode;
  actions?: ReactNode;
  /** Overrides the route-derived title (rare — prefer the table above). */
  title?: string;
  /** Optional contextual overline above the title. */
  eyebrow?: ReactNode;
  /** Allows an entity-owned screen to keep only its own visible title. */
  showTitle?: boolean;
  className?: string;
}>) {
  const pathname = usePathname() ?? '';
  const resolved = title ?? resolveTitle(pathname);
  const paintTitle = showTitle ?? !/^\/site\/crawls\/[^/]+\/pages\/[^/]+/.test(pathname);

  const heading = (
    <h1
      className={cn(
        paintTitle
          ? cn(displayHeadingXlClasses, 'min-w-0 flex-1 [overflow-wrap:break-word]')
          : 'sr-only',
      )}
    >
      {resolved}
    </h1>
  );

  // Explicitly hidden titles still retain the accessible page landmark.
  if (!paintTitle && !summary && !actions && !eyebrow) return heading;

  return (
    <div className={cn('mb-8 flex flex-col gap-2', className)}>
      {eyebrow ? <p className={eyebrowClasses}>{eyebrow}</p> : null}
      <div className="flex flex-nowrap items-start justify-between gap-4">
        {heading}
        {actions ? (
          <div className="ms-auto flex shrink-0 items-center gap-2.5 ps-4">{actions}</div>
        ) : null}
      </div>
      {summary ? (
        <p className="text-muted max-w-[72ch] text-sm leading-relaxed">{summary}</p>
      ) : null}
    </div>
  );
}
