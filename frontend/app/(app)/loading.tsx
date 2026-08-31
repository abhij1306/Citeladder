import { Skeleton } from '@/components/ui/skeleton';

/**
 * Immediate destination shell for a cold application-route navigation.
 * The shared sidebar and top bar stay mounted in `(app)/layout.tsx`; only the
 * route-owned content column enters this stable loading state.
 */
export default function AppRouteLoading() {
  return (
    <output className="grid gap-[var(--workspace-gap)]" aria-label="Loading destination">
      <div className="flex items-center justify-between gap-4">
        <Skeleton className="h-10 w-56 max-w-2/3" />
        <Skeleton className="h-9 w-28" />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
      <Skeleton className="h-72 w-full" />
    </output>
  );
}
