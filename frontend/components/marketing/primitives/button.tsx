import { ArrowRight } from 'lucide-react';
import Link from 'next/link';
import type { ComponentPropsWithoutRef, ReactNode } from 'react';

import { Button as SharedButton } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type Variant = 'primary' | 'dark' | 'nav' | 'ghost';
type VisualProps = Readonly<{ variant?: Variant; className?: string }>;

const sharedVariant = (variant: Variant) =>
  variant === 'ghost' ? 'ghost' : variant === 'primary' ? 'primary' : 'secondary';

const marketingSecondary =
  'border-border-strong bg-panel hover:border-border-bold hover:bg-background-alt shadow-xs';

export function ButtonLink({
  href,
  variant = 'primary',
  className,
  children,
  ...rest
}: VisualProps & { href: string; children: ReactNode } & Omit<
    ComponentPropsWithoutRef<'a'>,
    'href' | 'className' | 'children'
  >) {
  return (
    <SharedButton
      asChild
      variant={sharedVariant(variant)}
      className={cn(
        '[&_svg]:size-4 [&_svg]:shrink-0',
        (variant === 'dark' || variant === 'nav') && marketingSecondary,
        className,
      )}
    >
      <Link href={href} {...rest}>
        {children}
      </Link>
    </SharedButton>
  );
}

export function TextLink({
  href,
  className,
  children,
  ...rest
}: { href: string; className?: string; children: ReactNode } & Omit<
  ComponentPropsWithoutRef<'a'>,
  'href' | 'className' | 'children'
>) {
  return (
    <Link
      href={href}
      className={cn(
        'text-accent-text hover:text-accent-hover inline-flex items-center gap-2 font-medium',
        '[&_svg]:size-4 [&_svg]:shrink-0',
        className,
      )}
      {...rest}
    >
      {children}
    </Link>
  );
}

type IconButtonVariant = 'default' | 'dark' | 'nav';
type IconButtonSide = 'left' | 'right';

type IconButtonProps = Readonly<{
  title: string;
  variant?: IconButtonVariant;
  side?: IconButtonSide;
  icon?: ReactNode;
  className?: string;
}>;

export function IconButtonLink({
  href,
  openInNewTab = false,
  rel,
  title,
  variant = 'default',
  side = 'right',
  icon,
  className,
  ...rest
}: IconButtonProps & { href: string; openInNewTab?: boolean } & Omit<
    ComponentPropsWithoutRef<'a'>,
    'href' | 'target' | 'className' | 'children' | 'title'
  >) {
  const targetProps = openInNewTab
    ? { target: '_blank' as const, rel: rel ?? 'noopener noreferrer' }
    : { rel };
  const arrow = icon ?? <ArrowRight aria-hidden className="size-4" />;
  return (
    <SharedButton
      asChild
      variant={variant === 'default' ? 'primary' : 'secondary'}
      className={cn(variant !== 'default' && marketingSecondary, className)}
    >
      <Link href={href} {...targetProps} {...rest}>
        {side === 'left' ? arrow : null}
        <span>{title}</span>
        {side === 'right' ? arrow : null}
      </Link>
    </SharedButton>
  );
}
