import type { ReactNode } from 'react';

/**
 * The hero's on-load entrance. Animates purely additive over content that is
 * already server-rendered in its settled state.
 */
export function HeroEntrance({
  children,
  className,
}: Readonly<{
  children: ReactNode;
  className?: string;
}>) {
  return <div className={className}>{children}</div>;
}
