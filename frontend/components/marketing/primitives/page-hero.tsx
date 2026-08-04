import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';
import { BrandAtmosphere } from '@/components/ui/brand-atmosphere';

import { Eyebrow } from './label';
import { Container } from './section';
import { Reveal } from './reveal';

/**
 * Subpage opener. Every marketing route that is not `/` starts with exactly
 * this block, so /pricing, /faq, /solutions and the rest share one entry
 * rhythm instead of each inventing its own hero height and measure.
 */
export function PageHero({
  eyebrow,
  title,
  accent,
  lead,
  children,
  centered = false,
}: Readonly<{
  eyebrow: string;
  title: ReactNode;
  /** Trailing clause rendered in the display accent — optional by design. */
  accent?: string;
  lead?: ReactNode;
  children?: ReactNode;
  centered?: boolean;
}>) {
  return (
    <header className="citeladder-field-hero citeladder-grid-field relative overflow-hidden pt-16 pb-16 md:pt-30 md:pb-20">
      <BrandAtmosphere variant="page" />
      <Container className="relative z-1">
        <Reveal className={cn('max-w-5xl', centered && 'mx-auto text-center')}>
          <Eyebrow>{eyebrow}</Eyebrow>
          <h1
            className={cn(
              'font-display text-foreground mt-8 mb-8 max-w-[32ch] text-5xl',
              centered && 'mx-auto',
            )}
          >
            {title}
            {accent && (
              <>
                {' '}
                <em className="citeladder-keyword not-italic">{accent}</em>
              </>
            )}
          </h1>
          {lead && (
            <p className={cn('text-muted max-w-[80ch] text-lg', centered && 'mx-auto')}>{lead}</p>
          )}
          {children}
        </Reveal>
      </Container>
    </header>
  );
}
