import { LogoMark } from '@/components/ui/logo-mark';
import { cn } from '@/lib/utils';

/** Shared marketing mark and wordmark. */
export function Wordmark({ className }: Readonly<{ className?: string }>) {
  return (
    <span
      className={cn(
        'font-display text-foreground inline-flex items-center gap-2 text-xl leading-none font-bold tracking-tight',
        className,
      )}
    >
      <LogoMark size={16} />
      CiteLadder
    </span>
  );
}
