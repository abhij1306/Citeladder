'use client';

import { useQuery } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { DiscoveryModelCard } from '@/components/providers/discovery-model-card';
import { EngineCard } from '@/components/providers/engine-card';
import { providersApi } from '@/lib/api/providers';
import { queryKeys } from '@/lib/api/query-keys';
import { buildEngineCards } from '@/lib/providers/catalog';

/**
 * BYOK Provider Settings panel (F8, v2 direct-provider retirement) — rendered
 * inside the Settings screen's "Provider Settings" tab (formerly the
 * settings-owned Providers tab).
 *
 * Renders one card per logical engine (ChatGPT / Gemini / Claude), each served
 * by a single fixed direct transport (ChatGPT/OpenAI, Gemini/Google,
 * Claude/Anthropic). Each card takes a write-only API key (the stored secret is
 * never displayed), runs a connection test, and shows a `configured` badge from
 * `api_key_set`. Below, a plumbing-only discovery/analysis model selector.
 * Available transports and models are driven entirely by `/provider-catalog`.
 */
export function ProviderSettings() {
  const catalogQuery = useQuery({
    queryKey: queryKeys.providers.catalog(),
    queryFn: ({ signal }) => providersApi.getCatalog({ signal }),
  });

  const connectionsQuery = useQuery({
    queryKey: queryKeys.providers.connections(),
    queryFn: ({ signal }) => providersApi.listConnections({ signal }),
  });

  // The AUTHENTICATED four-state projection. A failure here leaves every card
  // at its fail-closed default (`missing`) rather than implying `connected`.
  const statesQuery = useQuery({
    queryKey: queryKeys.providers.states(),
    queryFn: ({ signal }) => providersApi.getConnectionStates({ signal }),
  });

  const cards = buildEngineCards(catalogQuery.data, statesQuery.data?.providers);
  const connections = connectionsQuery.data ?? [];
  const isLoading = catalogQuery.isLoading || connectionsQuery.isLoading;
  const isError = catalogQuery.isError || connectionsQuery.isError;

  return (
    <div className="grid gap-[var(--workspace-gap)]" data-tour="provider-settings">
      <p className="text-secondary max-w-2xl text-sm">
        Bring your own API keys — save one per engine, then run a connection test. Keys are
        write-only.
      </p>

      {isError ? (
        <Alert tone="danger">
          Could not load provider settings. Check your connection and try again.
        </Alert>
      ) : null}

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Card key={i}>
              <CardContent className="grid gap-3">
                <Skeleton className="h-5 w-24" />
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {cards.map((model) => (
            <EngineCard key={model.logical_engine} model={model} connections={connections} />
          ))}
        </div>
      )}

      <DiscoveryModelCard catalog={catalogQuery.data} />
    </div>
  );
}
