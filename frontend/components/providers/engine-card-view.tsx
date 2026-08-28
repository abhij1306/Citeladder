import { Badge } from '@/components/ui/badge';
import { BrandLogo } from '@/components/ui/brand-logo';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  ENGINE_DOMAINS,
  ENGINE_LOGOS,
  isConnectable,
  type EngineCardModel,
} from '@/lib/providers/catalog';
import type { useEngineConnection } from '@/lib/providers/use-engine-connection';

import { EngineConnectionFields } from './engine-connection-fields';

type ConnectionState = ReturnType<typeof useEngineConnection>;

function ConnectionStateBadge({ model }: Readonly<{ model: EngineCardModel }>) {
  const badge =
    model.state === 'connected'
      ? { value: 'success' as const, label: 'Connected' }
      : model.state === 'failed'
        ? { value: 'danger' as const, label: 'Failed' }
        : null;
  return badge ? (
    <Badge variant="status" value={badge.value}>
      {badge.label}
    </Badge>
  ) : (
    <Badge variant="neutral">{model.state === 'unavailable' ? 'Coming soon' : 'Missing'}</Badge>
  );
}

function ConnectionError({ model }: Readonly<{ model: EngineCardModel }>) {
  if (model.state === 'failed' && model.latest_probe) {
    return (
      <p className="text-danger-text text-xs">
        Last test failed
        {model.latest_probe.safe_reason ? `: ${model.latest_probe.safe_reason}` : ''}
        {model.latest_probe.model ? ` (model ${model.latest_probe.model})` : ''}.
      </p>
    );
  }
  if (model.availability === 'unavailable') {
    return (
      <p className="text-muted text-xs">
        {model.unavailable_reason === 'adapter_not_shipped'
          ? 'Coming soon — this provider has no adapter yet and cannot be connected.'
          : (model.unavailable_reason ?? 'Not available for connection.')}
      </p>
    );
  }
  return null;
}

function RouteDetails({ state }: Readonly<{ state: ConnectionState }>) {
  if (!state.route) return null;
  return (
    <div className="bg-background-alt border-border-subtle grid gap-1.5 rounded-md border p-3">
      <div className="flex items-center justify-between">
        <span className="text-muted text-2xs font-semibold">Route</span>
        <span className="text-foreground text-xs font-medium">{state.route.label}</span>
      </div>
      <div className="text-muted text-2xs grid gap-1 font-mono">
        <div className="flex items-center justify-between">
          <span>Model</span>
          <span className="text-secondary">{state.route.model}</span>
        </div>
      </div>
    </div>
  );
}

function ConnectionControls({ state }: Readonly<{ state: ConnectionState }>) {
  const { transport, configured, apiKey, saveMutation, testMutation, busy } = state;
  return (
    <div className="grid gap-3 pt-1">
      <EngineConnectionFields state={state} />
      <div className="flex items-center gap-2 pt-1">
        <Button
          type="button"
          size="sm"
          onClick={() => saveMutation.mutate()}
          disabled={busy || !transport || (!apiKey && !configured)}
        >
          {saveMutation.isPending ? 'Saving & testing…' : configured ? 'Update key' : 'Save key'}
        </Button>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => testMutation.mutate()}
          disabled={busy || !state.connection}
        >
          {testMutation.isPending ? 'Testing…' : 'Test connection'}
        </Button>
      </div>
    </div>
  );
}

export function EngineCardView({
  model,
  connectionState,
}: Readonly<{ model: EngineCardModel; connectionState: ConnectionState }>) {
  return (
    <Card className="flex flex-col justify-between">
      <div>
        <CardHeader className="flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <BrandLogo
              name={model.label}
              logoUrl={ENGINE_LOGOS[model.logical_engine]}
              websiteUrl={ENGINE_DOMAINS[model.logical_engine]}
              size="sm"
            />
            <h3 className="text-foreground text-heading-sm font-semibold">{model.label}</h3>
          </div>
          <ConnectionStateBadge model={model} />
        </CardHeader>
        <CardContent className="grid gap-3">
          <ConnectionError model={model} />
          <RouteDetails state={connectionState} />
          {isConnectable(model) ? <ConnectionControls state={connectionState} /> : null}
        </CardContent>
      </div>
    </Card>
  );
}
