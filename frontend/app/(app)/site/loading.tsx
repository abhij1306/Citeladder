import { ScreenSkeleton } from '@/components/site-health/screen-states';

/** Immediate App Router fallback while the Website route chunk initializes. */
export default function SiteLoading() {
  return <ScreenSkeleton label="Loading Website…" />;
}
