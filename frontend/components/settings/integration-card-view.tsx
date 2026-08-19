import { Info } from 'lucide-react';

import { ConnectionRow } from '@/components/settings/integration-connection-row';
import { FAMILY_META, type GrantFamily, type GrantModel } from '@/components/settings/grant-model';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardEyebrow, CardHeader } from '@/components/ui/card';
import { integrationsApi, type IntegrationConnection } from '@/lib/api/integrations';
import { assignLocation } from '@/lib/navigate';

type GrantStatus = IntegrationConnection['grant_status'];
type GrantBadge =
  { variant: 'status'; value: 'success' | 'warning' | 'danger' } | { variant: 'neutral' };

const GRANT_STATUS_BADGE: Record<GrantStatus, GrantBadge> = {
  connected: { variant: 'status', value: 'success' },
  needs_reauth: { variant: 'status', value: 'warning' },
  pending_revocation: { variant: 'status', value: 'warning' },
  error: { variant: 'status', value: 'danger' },
  revoked: { variant: 'neutral' },
};

const GRANT_STATUS_LABEL: Record<GrantStatus, string> = {
  connected: 'Connected',
  needs_reauth: 'Needs reauth',
  pending_revocation: 'Pending revocation',
  error: 'Error',
  revoked: 'Revoked',
};

function GrantAlert({ family, status }: Readonly<{ family: GrantFamily; status: GrantStatus }>) {
  const title = FAMILY_META[family].title;

  if (status === 'needs_reauth') {
    return (
      <Alert tone="warning">
        {title} requires renewed consent for this grant. Reconnect to resume syncing — previously
        imported data is unaffected.
      </Alert>
    );
  }
  if (status === 'error') {
    return (
      <Alert tone="danger">
        The last connection test failed — {title}&nbsp;rejected this grant&rsquo;s refresh.
        Reconnect to resume syncing.
      </Alert>
    );
  }
  if (status === 'pending_revocation') {
    return (
      <Alert tone="warning">
        Disconnect is finishing — CiteLadder is retrying the {title} revocation in the background.
        Previously imported data is kept.
      </Alert>
    );
  }
  if (status === 'revoked') {
    return (
      <Alert tone="neutral">This grant was revoked at {title}. Reconnect to resume syncing.</Alert>
    );
  }

  return null;
}

function GrantHeader({
  family,
  grant,
}: Readonly<{ family: GrantFamily; grant: GrantModel | null }>) {
  const meta = FAMILY_META[family];
  const badge = grant ? GRANT_STATUS_BADGE[grant.status] : { variant: 'neutral' as const };
  const label = grant ? GRANT_STATUS_LABEL[grant.status] : 'Not connected';

  return (
    <CardHeader className="border-border-subtle flex-row items-center justify-between gap-3 border-b pb-3">
      <div className="grid min-w-0 gap-0.5">
        <CardEyebrow>OAuth grant</CardEyebrow>
        <h3 className="text-foreground text-heading-sm font-semibold">{meta.title}</h3>
        <p className="text-muted truncate text-xs">{meta.blurb}</p>
      </div>
      <div className="shrink-0">
        {badge.variant === 'status' ? (
          <Badge variant="status" value={badge.value} data-testid={`grant-status-${family}`}>
            {label}
          </Badge>
        ) : (
          <Badge variant="neutral" data-testid={`grant-status-${family}`}>
            {label}
          </Badge>
        )}
      </div>
    </CardHeader>
  );
}

function ConnectCard({ family }: Readonly<{ family: GrantFamily }>) {
  const meta = FAMILY_META[family];

  return (
    <Card data-testid={`grant-card-${family}`} className="flex flex-col justify-between">
      <div>
        <GrantHeader family={family} grant={null} />
        <CardContent className="pt-4">
          <p className="text-secondary text-sm">
            Connect your {meta.title} account to automatically import traffic and search visibility
            metrics.
          </p>
        </CardContent>
      </div>
      <CardContent className="pt-0">
        <Button
          variant="secondary"
          onClick={() => assignLocation(integrationsApi.oauthStartUrl(meta.connectProvider))}
        >
          Connect {meta.title}
        </Button>
      </CardContent>
    </Card>
  );
}

function ConnectedCard({ family, grant }: Readonly<{ family: GrantFamily; grant: GrantModel }>) {
  const meta = FAMILY_META[family];

  return (
    <Card data-testid={`grant-card-${family}`} className="flex flex-col justify-between">
      <div>
        <GrantHeader family={family} grant={grant} />
        <CardContent className="grid gap-3 pt-4">
          <GrantAlert family={family} status={grant.status} />
          <div className="bg-well/60 border-border-subtle text-muted flex items-center gap-2 rounded-md border px-3 py-2 text-xs">
            <Info className="text-secondary size-3.5 shrink-0" aria-hidden />
            <span>
              One OAuth grant shared by {grant.connections.length}{' '}
              {grant.connections.length === 1 ? 'connection' : 'connections'}.
            </span>
          </div>
          <div className="grid gap-3">
            {grant.connections.map((connection) => (
              <ConnectionRow key={connection.id} connection={connection} grant={grant} />
            ))}
          </div>
        </CardContent>
      </div>
      <CardContent className="pt-0">
        <div className="border-border-subtle flex flex-wrap items-center justify-between gap-2 border-t pt-3">
          <Button
            variant={grant.status === 'connected' ? 'secondary' : 'primary'}
            size="sm"
            onClick={() => assignLocation(integrationsApi.oauthStartUrl(meta.connectProvider))}
          >
            Reconnect
          </Button>
          <span className="text-muted text-right text-xs">
            Reconnecting renews consent for the whole grant.
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

export function IntegrationCardView({
  family,
  grant,
}: Readonly<{ family: GrantFamily; grant: GrantModel | null }>) {
  return grant ? <ConnectedCard family={family} grant={grant} /> : <ConnectCard family={family} />;
}
