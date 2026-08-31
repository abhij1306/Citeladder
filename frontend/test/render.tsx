import { QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderOptions } from '@testing-library/react';
import { domAnimation, LazyMotion } from 'motion/react';
import type { ReactElement, ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';
import { createAppQueryClient } from '@/lib/api/query-client';

/**
 * Render a component inside a fresh TanStack Query provider (F4 tests). A new
 * client per render keeps cache state isolated between tests, and the shared
 * factory means the real retry policy applies.
 *
 * A TooltipProvider is included because every app route mounts one — without
 * it a component that renders a Tooltip throws under test but works in the
 * app, which is a failure mode of the harness rather than the component.
 */
export function renderWithProviders(ui: ReactElement, options?: Omit<RenderOptions, 'wrapper'>) {
  const queryClient = createAppQueryClient();

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <LazyMotion features={domAnimation} strict>
          <TooltipProvider>{children}</TooltipProvider>
        </LazyMotion>
      </QueryClientProvider>
    );
  }

  return { queryClient, ...render(ui, { wrapper: Wrapper, ...options }) };
}
