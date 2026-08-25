import { LogoMark } from '@/components/ui/logo-mark';
import { cn } from '@/lib/utils';

/** Shared marketing mark and wordmark. */
export function Wordmark({ className }: Readonly<{ className?: string }>) {
  return (
    <span className={cn('inline-flex items-center', className)}>
      <LogoMark size={24} />
    </span>
  );
}
