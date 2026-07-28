'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { driver } from 'driver.js';
import 'driver.js/dist/driver.css';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';

import { workspacesApi } from '@/lib/api/workspaces';
import { queryKeys } from '@/lib/api/query-keys';
import type { ProductTourStatus } from '@/lib/api/types';
import { useProjectContext } from '@/lib/project/project-context';

const TOUR_VERSION = 'dashboard-v1';

type TourStep = {
  id: string;
  path: string;
  selector: string;
  title: string;
  description: string;
  /** Preferred popover placement relative to the highlighted target. */
  side?: 'top' | 'right' | 'bottom' | 'left';
  align?: 'start' | 'center' | 'end';
};

/** Versioned, route-aware catalog. Targets are stable `data-tour` hooks, never CSS layout classes. */
export const PRODUCT_TOUR_STEPS: readonly TourStep[] = [
  {
    id: 'dashboard-overview',
    path: '/projects',
    selector: '[data-tour="dashboard-overview"]',
    title: 'Your Dashboard',
    description: 'Your active project at a glance — every card links to its evidence.',
    side: 'bottom',
    align: 'start',
  },
  {
    id: 'dashboard-report',
    path: '/projects',
    selector: '[data-tour="dashboard-report"]',
    title: 'Share an executive report',
    description: 'Download a PDF built from persisted results — never a live provider call.',
    side: 'bottom',
    align: 'end',
  },
  {
    id: 'provider-settings',
    path: '/settings?tab=providers',
    selector: '[data-tour="provider-settings"]',
    title: 'Connect answer engines',
    description: 'Add provider keys before launching an audit. Keys are write-only.',
    side: 'top',
    align: 'center',
  },
] as const;

function stepAt(id: string | null | undefined) {
  return PRODUCT_TOUR_STEPS.find((step) => step.id === id) ?? PRODUCT_TOUR_STEPS[0];
}

function isCurrentStepLocation(pathname: string, search: string, stepPath: string) {
  const expected = new URL(stepPath, 'https://searchify.local');
  return pathname === expected.pathname && search === expected.search.slice(1);
}

/** Persists product-tour progress and resumes it after each App Router transition. */
export function ProductTourProvider({ children }: Readonly<{ children: ReactNode }>) {
  const router = useRouter();
  const pathname = usePathname() ?? '';
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  const queryClient = useQueryClient();
  const { activeProject } = useProjectContext();
  const workspaceId = activeProject?.workspace_id ?? null;
  const renderedStep = useRef<string | null>(null);
  const transitioning = useRef(false);
  const [targetRetry, setTargetRetry] = useState(0);

  const tourQuery = useQuery({
    queryKey: queryKeys.workspaces.productTour(workspaceId ?? ''),
    queryFn: ({ signal }) => workspacesApi.getProductTour(workspaceId!, { signal }),
    enabled: Boolean(workspaceId),
  });
  const update = useMutation({
    mutationFn: (payload: { status: ProductTourStatus; step_id?: string | null }) =>
      workspacesApi.updateProductTour(workspaceId!, { version: TOUR_VERSION, ...payload }),
    onSuccess: (tour) => {
      queryClient.setQueryData(queryKeys.workspaces.productTour(workspaceId ?? ''), tour);
      renderedStep.current = null;
      transitioning.current = false;
      setTargetRetry(0);
    },
  });

  const persist = useCallback(
    async (status: ProductTourStatus, stepId?: string | null) => {
      if (!workspaceId || update.isPending) return;
      await update.mutateAsync({ status, step_id: stepId });
    },
    [update, workspaceId],
  );

  const replay = useCallback(() => {
    void persist('in_progress', PRODUCT_TOUR_STEPS[0].id);
  }, [persist]);

  useEffect(() => {
    window.addEventListener('searchify:replay-product-tour', replay);
    return () => window.removeEventListener('searchify:replay-product-tour', replay);
  }, [replay]);

  useEffect(() => {
    let retryTimeout: number | undefined;
    let instance: ReturnType<typeof driver> | null = null;
    let instanceDestroyed = false;
    const destroyInstance = () => {
      if (!instance || instanceDestroyed) return;
      instanceDestroyed = true;
      instance.destroy();
      if (renderedStep.current === stepAt(tourQuery.data?.step_id).id) {
        renderedStep.current = null;
      }
    };
    const cleanup = () => {
      if (retryTimeout !== undefined) window.clearTimeout(retryTimeout);
      destroyInstance();
    };

    const tour = tourQuery.data;
    if (!tour || update.isPending) return cleanup;
    if (tour.status === 'not_started') {
      void persist('in_progress', PRODUCT_TOUR_STEPS[0].id);
      return cleanup;
    }
    if (tour.status !== 'in_progress') return cleanup;

    const step = stepAt(tour.step_id);
    // Navigate before looking for the hook. The previous ordering searched the
    // current page first; after step two the provider-settings hook was absent,
    // so the tour only retried and then silently disappeared.
    if (!isCurrentStepLocation(pathname, search, step.path)) {
      router.push(step.path);
      return cleanup;
    }
    const target = document.querySelector<HTMLElement>(step.selector);
    if (!target) {
      if (targetRetry < 12) {
        retryTimeout = window.setTimeout(() => setTargetRetry((value) => value + 1), 100);
      }
      return cleanup;
    }
    if (renderedStep.current === step.id) return cleanup;

    renderedStep.current = step.id;
    const stepIndex = PRODUCT_TOUR_STEPS.findIndex((candidate) => candidate.id === step.id);
    instance = driver({
      animate: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
      allowClose: true,
      allowKeyboardControl: true,
      // The scrim token carries its own alpha (light 49% / dark 60%), so the
      // library's additional opacity multiply stays at 1. Applied as the
      // overlay SVG's inline fill, the var() resolves per active theme.
      overlayColor: 'var(--overlay-scrim)',
      overlayOpacity: 1,
      // Themed via app/tour.css (.driver-popover.searchify-tour).
      popoverClass: 'searchify-tour',
      popoverOffset: 12,
      stagePadding: 6,
      stageRadius: 12,
      showProgress: true,
      progressText: '{{current}} of {{total}}',
      // We drive step-by-step with highlight() rather than a steps array, so
      // the library cannot compute {{current}}/{{total}} itself — stamp the
      // progress readout when the popover renders.
      onPopoverRender: (popover) => {
        popover.progress.textContent = `${stepIndex + 1} of ${PRODUCT_TOUR_STEPS.length}`;
      },
      onNextClick: () => {
        transitioning.current = true;
        destroyInstance();
        const next = PRODUCT_TOUR_STEPS[stepIndex + 1];
        void persist(next ? 'in_progress' : 'completed', next?.id ?? null);
      },
      onPrevClick: () => {
        const previous = PRODUCT_TOUR_STEPS[Math.max(0, stepIndex - 1)];
        if (previous.id === step.id) return;
        transitioning.current = true;
        destroyInstance();
        void persist('in_progress', previous.id);
      },
      onDestroyStarted: () => {
        if (!transitioning.current) void persist('skipped');
        destroyInstance();
      },
    });
    instance.highlight({
      element: target,
      popover: {
        title: step.title,
        description: step.description,
        side: step.side,
        align: step.align,
        showButtons: ['previous', 'next', 'close'],
        nextBtnText: stepIndex === PRODUCT_TOUR_STEPS.length - 1 ? 'Done' : 'Next',
      },
    });
    return cleanup;
  }, [pathname, persist, router, search, targetRetry, tourQuery.data, update.isPending]);

  return children;
}
