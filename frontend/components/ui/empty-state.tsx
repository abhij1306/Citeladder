import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

import { Card, CardContent } from '@/components/ui/card';
import { IconChip } from '@/components/ui/icon-chip';
import { displayHeadingLgClasses } from '@/components/ui/typography';

/**
 * EmptyState — the one empty-state pattern for the whole app.
 *
 * Replaces the per-surface empty states that had each grown their own copy and
 * layout. Shape: icon chip → heading → one short line → one action.
 *
 * **Keep `description` to a single sentence.** The empty states this replaces
 * had drifted into two- and three-clause explanations of what the screen would
 * eventually contain, which is what made them feel crowded. Say what is missing
 * and what to do about it; the screen itself explains the rest once it has
 * data. The prop is optional precisely so surfaces can omit it when the
 * heading already says everything.
 *
 * `action` is a single primary control. Pass a second one only when both are
 * genuinely equal choices — otherwise the secondary path belongs in the body of
 * the screen, not in its empty state.
 */
export function EmptyState({
  icon: Icon,
  heading,
  description,
  action,
  footnote,
  className,
}: Readonly<{
  icon: LucideIcon;
  heading: string;
  /** One sentence. See the note above before making it two. */
  description?: string;
  action?: ReactNode;
  /** Small muted line below the action (e.g. a support correlation reference). */
  footnote?: ReactNode;
  className?: string;
}>) {
  return (
    <Card className={className}>
      <CardContent className="grid justify-items-center gap-4 py-[var(--empty-state-padding)] text-center">
        <IconChip>
          <Icon className="size-6" aria-hidden />
        </IconChip>
        <div className="grid gap-2">
          <h2 className={displayHeadingLgClasses}>{heading}</h2>
          {description ? (
            <p className="text-secondary mx-auto max-w-[46ch] text-sm">{description}</p>
          ) : null}
        </div>
        {action ? <div className="mt-2 flex items-center gap-2">{action}</div> : null}
        {footnote ? <div className="text-muted text-2xs">{footnote}</div> : null}
      </CardContent>
    </Card>
  );
}
