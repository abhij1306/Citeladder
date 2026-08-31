import Link from 'next/link';

import { LogoMark } from '@/components/ui/logo-mark';

export function AuthWordmark({
  compact = false,
  size,
}: Readonly<{ compact?: boolean; size?: number }>) {
  return (
    <Link
      href="/"
      aria-label="CiteLadder home"
      className="group inline-flex items-center no-underline transition-opacity hover:opacity-90"
    >
      <LogoMark size={size ?? (compact ? 22 : 26)} />
    </Link>
  );
}
