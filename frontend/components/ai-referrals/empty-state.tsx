import Link from 'next/link';
import { BarChart3 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';

/**
 * Empty state for `/ai-referrals`. Referral measurement begins only after a
 * persisted GA4 source/medium report has been synced.
 */
export function AiReferralsEmptyState() {
  return (
    <EmptyState
      icon={BarChart3}
      heading="No AI-referral data yet"
      description="Connect Google Analytics 4 and sync traffic to see which known AI sources send sessions."
      action={
        <Button asChild size="md">
          <Link href="/settings?tab=integrations">Open integration settings</Link>
        </Button>
      }
    />
  );
}
