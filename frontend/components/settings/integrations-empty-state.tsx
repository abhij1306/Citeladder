'use client';

import { Unplug } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { integrationsApi } from '@/lib/api/integrations';
import { assignLocation } from '@/lib/navigate';

/**
 * Empty state for the Settings → Integrations tab when the workspace has no
 * connections yet (mockup `integrations-settings-empty-first-run-*.html`), in
 * the `VisibilityEmptyState` pattern (mono eyebrow + IconChip + display
 * heading + CTAs).
 *
 * Both CTAs are full-page navigations to the same-origin OAuth start
 * endpoints (302s — never apiClient fetches): one Google consent links Search
 * Console + Analytics 4 on a shared grant; Microsoft links Bing Webmaster
 * Tools.
 */
export function IntegrationsEmptyState() {
  return (
    <div data-testid="integrations-empty-state">
      <EmptyState
        icon={Unplug}
        heading="No integrations connected"
        description="Connect Google Analytics 4 for AI Referrals. Connect Google or Microsoft for Traffic."
        action={
          <>
            <Button size="md" onClick={() => assignLocation(integrationsApi.oauthStartUrl('gsc'))}>
              Connect Google
            </Button>
            <Button
              variant="ghost"
              size="md"
              onClick={() => assignLocation(integrationsApi.oauthStartUrl('bing'))}
            >
              Connect Microsoft
            </Button>
          </>
        }
      />
    </div>
  );
}
