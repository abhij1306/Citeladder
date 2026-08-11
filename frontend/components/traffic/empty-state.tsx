import Link from 'next/link';
import { Plug } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';

/**
 * Empty state for a project with no persisted Traffic snapshot. Traffic renders
 * persisted sync projections only, so there is nothing to show until an
 * integration syncs. When connections already exist (`hasConnections`) the copy
 * switches from "connect one" to "the first sync is on its way" — the CTA lands
 * on Settings → Integrations either way.
 *
 * Copy is one line per state. Both previously opened with the same sentence
 * enumerating what Traffic projects (impressions, clicks, sessions,
 * conversions, organic vs AI-driven) before saying what to do about it — the
 * screen shows all of that as soon as it has data.
 */
export function TrafficEmptyState({
  hasConnections = false,
  syncing = false,
  onSyncNow,
}: Readonly<{
  hasConnections?: boolean;
  syncing?: boolean;
  onSyncNow?: () => void;
}>) {
  return (
    <EmptyState
      icon={Plug}
      heading={hasConnections ? 'Sync your traffic data' : 'Connect search data'}
      description={
        hasConnections
          ? 'Your connection is ready. Run a sync to import Search Console and Analytics data.'
          : 'Connect Search Console or Google Analytics 4 to see organic and AI-driven traffic.'
      }
      action={
        hasConnections && onSyncNow ? (
          <Button onClick={onSyncNow} disabled={syncing} size="md">
            {syncing ? 'Syncing…' : 'Sync now'}
          </Button>
        ) : (
          <Button asChild size="md">
            <Link href="/settings?tab=integrations">Connect an integration</Link>
          </Button>
        )
      }
    />
  );
}
