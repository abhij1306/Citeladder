import { LogoMark } from '@/components/ui/logo-mark';
import { cn } from '@/lib/utils';

/**
 * The CiteLadder mark: a lens with a lit centre — "observe, then show the
 * proof". Geometry is shared verbatim with the app wordmark so the two
 * surfaces stay one brand even though they run different design systems.
 */
function BrandMark({ className }: Readonly<{ className?: string }>) {
  return (
    <span aria-hidden="true" className={cn('inline-flex shrink-0', className)}>
      <LogoMark size={32} />
    </span>
  );
}

/** Mark + wordmark. `as` keeps the single-h1 rule intact on every page. */
export function Wordmark({ className }: Readonly<{ className?: string }>) {
  return (
    <span
      className={cn(
        'font-display text-foreground inline-flex items-center gap-4 text-lg',
        className,
      )}
    >
      <BrandMark />
      CiteLadder
    </span>
  );
}
