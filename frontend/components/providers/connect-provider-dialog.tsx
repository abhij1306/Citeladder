'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { BrandLogo } from '@/components/ui/brand-logo';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Select } from '@/components/ui/select';
import { providersApi } from '@/lib/api/providers';
import { queryKeys } from '@/lib/api/query-keys';
import type { LogicalEngine, ProviderConnection } from '@/lib/api/types';
import {
  buildEngineCards,
  isConnectable,
  connectionForTransport,
  ENGINE_DOMAINS,
  ENGINE_LOGOS,
  ENGINE_LABELS,
  ENGINE_ORDER,
  isVerified,
  TRANSPORT_LABELS,
  type EngineCardModel,
} from '@/lib/providers/catalog';
import { useEngineConnection } from '@/lib/providers/use-engine-connection';

import { EngineConnectionFields } from './engine-connection-fields';

/**
 * ConnectProviderDialog (Task 3.2) — the guided single-provider connect flow,
 * reusable from the Getting Started checklist and the launch dialog's "No
 * configured engines" empty state. One engine picker (driven by the provider
 * catalog), one write-only API-key field (never pre-filled — the stored
 * secret is never on the wire), an inline "Test connection" with the same
 * success/failure UX as the Settings engine cards, then Save. A successful
 * save invalidates the shared connections query (so callers like the launch
 * dialog see the new engine immediately) and closes. Full 3-engine management
 * stays in Settings → Providers.
 */
export function ConnectProviderDialog({
  open,
  onOpenChange,
  onConnected,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a key is saved successfully (the dialog closes first). */
  onConnected?: () => void;
}>) {
  const catalogQuery = useQuery({
    queryKey: queryKeys.providers.catalog(),
    queryFn: ({ signal }) => providersApi.getCatalog({ signal }),
    enabled: open,
  });
  const connectionsQuery = useQuery({
    queryKey: queryKeys.providers.connections(),
    queryFn: ({ signal }) => providersApi.listConnections({ signal }),
    enabled: open,
  });

  const cards = buildEngineCards(catalogQuery.data);
  const connections = connectionsQuery.data ?? [];

  // Reset the picker each time the dialog opens so it always lands on the
  // first engine that still needs a key (adjust-state-during-render pattern).
  const [selected, setSelected] = useState<LogicalEngine | null>(null);
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setSelected(null);
  }

  // Only connectable engines are candidates. Planned providers have no route,
  // so the old `card.route ? … : true` fallback selected one of them as soon
  // as all three shipped engines were configured — a default the engine
  // picker below cannot display, since it lists ENGINE_ORDER only.
  //
  // "Still needs attention" means UNVERIFIED, not key-less: an engine whose key
  // is stored but has never passed a probe cannot launch an audit, so it is
  // exactly what this dialog should open on.
  const connectableCards = cards.filter(isConnectable);
  const firstUnverified =
    connectableCards.find(
      (card) => !isVerified(connectionForTransport(connections, card.route!.transport_provider)),
    )?.logical_engine ?? ENGINE_ORDER[0];
  const engine = selected ?? firstUnverified;
  // Undefined while the catalog is still loading (no routes yet). The form is
  // withheld rather than rendered against a route-less placeholder.
  const model =
    connectableCards.find((card) => card.logical_engine === engine) ?? connectableCards[0];

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Connect a provider"
      description="Pick an AI engine and paste its API key. Saving runs a connection test — a key only becomes usable for audits once it passes. Keys are write-only: CiteLadder never displays a stored secret."
    >
      <div className="grid gap-4">
        <Field label="AI engine">
          {(props) => (
            <Select
              {...props}
              ariaLabel="AI engine"
              value={engine}
              onValueChange={setSelected}
              options={ENGINE_ORDER.map((key) => ({ value: key, label: ENGINE_LABELS[key] }))}
            />
          )}
        </Field>

        {model ? (
          <ConnectEngineForm
            key={engine}
            model={model}
            connections={connections}
            onCancel={() => onOpenChange(false)}
            onSaved={() => {
              onOpenChange(false);
              onConnected?.();
            }}
          />
        ) : (
          <p className="text-muted text-sm">Loading available engines…</p>
        )}
      </div>
    </Dialog>
  );
}

/**
 * Per-engine connect form. Keyed by the picked engine so switching engines
 * resets the typed key and test state. Save/test semantics mirror the
 * Settings engine card exactly via the shared `useEngineConnection` hook.
 */
function ConnectEngineForm({
  model,
  connections,
  onCancel,
  onSaved,
}: Readonly<{
  model: EngineCardModel;
  connections: ProviderConnection[];
  onCancel: () => void;
  onSaved: () => void;
}>) {
  const connectionState = useEngineConnection({ model, connections, onSaved });
  const { route, transport, connection, configured, apiKey, saveMutation, testMutation, busy } =
    connectionState;

  return (
    <div className="grid gap-4">
      {route ? (
        <div className="bg-background-alt border-border-subtle flex items-center justify-between rounded-md border p-3">
          <div className="flex items-center gap-2.5">
            <BrandLogo
              name={model.label}
              logoUrl={ENGINE_LOGOS[model.logical_engine]}
              websiteUrl={ENGINE_DOMAINS[model.logical_engine]}
              size="sm"
            />
            <div>
              <p className="text-foreground text-xs font-semibold">{model.label}</p>
              <p className="text-muted text-2xs">
                via {TRANSPORT_LABELS[route.transport_provider]}
              </p>
            </div>
          </div>
          <div className="text-muted text-2xs grid gap-0.5 text-right font-mono">
            <span className="text-secondary">{route.model}</span>
          </div>
        </div>
      ) : (
        <p className="text-muted text-sm">No route available for this engine.</p>
      )}

      <EngineConnectionFields state={connectionState} />

      <div className="flex items-center justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          variant="secondary"
          onClick={() => testMutation.mutate()}
          disabled={busy || !connection}
        >
          {testMutation.isPending ? 'Testing…' : 'Test connection'}
        </Button>
        <Button
          onClick={() => saveMutation.mutate()}
          disabled={busy || !transport || (!apiKey && !configured)}
        >
          {saveMutation.isPending ? 'Saving & testing…' : configured ? 'Update key' : 'Save key'}
        </Button>
      </div>
    </div>
  );
}
