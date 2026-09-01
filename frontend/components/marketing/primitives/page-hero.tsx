import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

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
    <header className="bg-background-alt relative overflow-hidden pt-16 pb-16 md:pt-30 md:pb-20">
      <Container className="relative z-1">
        <Reveal className={cn('max-w-5xl', centered && 'mx-auto text-center')}>
          <Eyebrow>{eyebrow}</Eyebrow>
          <h1
            className={cn(
              'website-page-title text-foreground mt-6 mb-6 max-w-[28ch] text-balance',
              centered && 'mx-auto',
            )}
          >
            {title}
            {accent && (
              <>
                {' '}
                <em className="text-accent-text not-italic">{accent}</em>
              </>
            )}
          </h1>
          {lead && (
            <p className={cn('website-lead text-muted max-w-[75ch]', centered && 'mx-auto')}>
              {lead}
            </p>
          )}
          {children}
        </Reveal>
      </Container>
    </header>
  );
}
