/**
 * Provider Settings view-model helpers (F8, v2 direct-provider retirement).
 *
 * Turns the raw `/provider-catalog` payload + the workspace's
 * `/provider-connections` into the per-engine card model the UI renders. The
 * catalog is the single source of truth for which (logical engine → transport →
 * model) routes are available. After the direct-provider retirement each
 * logical engine has exactly ONE direct transport — ChatGPT/OpenAI,
 * Gemini/Google, Claude/Anthropic — so each card renders a single fixed direct
 * route with no toggle and no reserved "coming soon" option.
 */
import type {
  LogicalEngine,
  ProviderCatalog,
  ProviderConnection,
  ProviderConnectionState,
  ProviderConnectionStateEntry,
  TransportProvider,
} from '@/lib/api/types';

/** Logical engines rendered as cards, in display order. */
export const ENGINE_ORDER: readonly LogicalEngine[] = ['chatgpt', 'gemini', 'claude'] as const;

/** Human display names for each logical engine. */
export const ENGINE_LABELS: Record<LogicalEngine, string> = {
  chatgpt: 'ChatGPT',
  gemini: 'Gemini',
  claude: 'Claude',
};

/** Human display names for each transport provider. */
export const TRANSPORT_LABELS: Record<TransportProvider, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
};

/** Domains for brand logo resolution via Logo.dev / BrandLogo. */
export const ENGINE_DOMAINS: Record<string, string> = {
  chatgpt: 'openai.com',
  gemini: 'google.com',
  claude: 'anthropic.com',
  grok: 'x.ai',
  perplexity: 'perplexity.ai',
  copilot: 'microsoft.com',
};

/** Local brand logo assets for engines when available. */
export const ENGINE_LOGOS: Record<string, string> = {
  claude: '/brand/claude.png',
  copilot: '/brand/copilot.jpg',
  grok: '/brand/grok.png',
  perplexity: '/brand/perplexity.png',
};

/** Human label for an engine key (falls back to the raw key). */
export function engineLabel(key: string): string {
  return ENGINE_LABELS[key as LogicalEngine] ?? key;
}

/** Human label for a transport key (falls back to the raw key). */
export function transportLabel(key: string): string {
  return TRANSPORT_LABELS[key as TransportProvider] ?? key;
}

/** The single fixed direct route on an engine card. */
type EngineRouteOption = {
  transport_provider: TransportProvider;
  model: string;
  /** Toggle-free label, e.g. "Direct (OpenAI)". */
  label: string;
};

/** The full view-model for one engine card. */
export type EngineCardModel = {
  logical_engine: LogicalEngine;
  label: string;
  /** The single direct route for this engine (null if the catalog omits it). */
  route: EngineRouteOption | null;
  /**
   * Whether this engine can be connected at all. A planned provider is
   * `unavailable` with `route: null`, which is what makes it non-connectable —
   * the card is keyboard-reachable and informative, but constructs no mutation.
   */
  availability: 'available' | 'unavailable';
  /** The backend's own reason token when unavailable. Never invented here. */
  unavailable_reason: string | null;
  /**
   * The AUTHENTICATED workspace state, distinct from availability. A provider
   * can be generally available and still `missing` for this workspace.
   */
  state: ProviderConnectionState;
  /** Safe probe/state reason from the authenticated projection. */
  safe_reason: string | null;
  latest_probe: ProviderConnectionStateEntry['latest_probe'];
};

/**
 * Planned providers. They exist as catalog presentation entries only: no
 * adapter, no route, and no transport enum entry, so nothing downstream can
 * resolve one to another provider. Keeping them visible is the approved
 * marketing exception; keeping them route-less is what makes it safe.
 */
const PLANNED_ENGINES = [
  { key: 'grok', label: 'Grok' },
  { key: 'perplexity', label: 'Perplexity' },
  { key: 'copilot', label: 'Copilot' },
] as const;

/** Display label for a direct transport route. */
function directLabel(transport: TransportProvider): string {
  return `Direct (${TRANSPORT_LABELS[transport]})`;
}

/**
 * Build the ordered engine card models.
 *
 * Shipped engines come first, each with its single direct route, then the
 * planned providers as keyboard-reachable unavailable cards.
 *
 * The authenticated `states` projection decides the four-state badge. It FAILS
 * CLOSED: without it, a configured key shows as `missing` rather than
 * `connected`, because "we stored a key" is not evidence that the key works —
 * only a successful probe is.
 */
export function buildEngineCards(
  catalog: ProviderCatalog | undefined,
  states?: readonly ProviderConnectionStateEntry[],
): EngineCardModel[] {
  const byEngine = new Map(catalog?.engines.map((e) => [e.logical_engine, e]) ?? []);
  const byKey = new Map((states ?? []).map((entry) => [entry.key, entry]));

  const shipped = ENGINE_ORDER.map((engine) => {
    const approved = byEngine.get(engine)?.routes ?? [];
    const approvedRoute = approved[0];
    const route: EngineRouteOption | null = approvedRoute
      ? {
          transport_provider: approvedRoute.transport_provider,
          model: approvedRoute.transport_model,
          label: directLabel(approvedRoute.transport_provider),
        }
      : null;
    const entry = byKey.get(engine) ?? byKey.get(`provider.${engine}`);
    return {
      logical_engine: engine,
      label: ENGINE_LABELS[engine],
      route,
      availability: route ? ('available' as const) : ('unavailable' as const),
      unavailable_reason: route ? null : 'route_not_published',
      state: entry?.state ?? ('missing' as const),
      safe_reason: entry?.safe_reason ?? null,
      latest_probe: entry?.latest_probe ?? null,
    };
  });

  const planned = PLANNED_ENGINES.map((provider) => {
    const entry = byKey.get(`provider.${provider.key}`);
    return {
      // Cast: a planned key is deliberately NOT in the transport/adapter enum,
      // so it can never be resolved to a connectable route.
      logical_engine: provider.key as LogicalEngine,
      label: provider.label,
      route: null,
      availability: 'unavailable' as const,
      unavailable_reason: entry?.safe_reason ?? 'adapter_not_shipped',
      state: 'unavailable' as const,
      safe_reason: entry?.safe_reason ?? null,
      latest_probe: null,
    };
  });

  return [...shipped, ...planned];
}

/** True when this card may construct a save/test mutation at all. */
export function isConnectable(model: EngineCardModel): boolean {
  return model.availability === 'available' && model.route !== null;
}

/**
 * Find the connection that serves a given transport in this workspace. BYOK
 * connections are keyed by `transport_provider`.
 */
export function connectionForTransport(
  connections: ProviderConnection[],
  transport: TransportProvider,
): ProviderConnection | undefined {
  return connections.find((c) => c.transport_provider === transport);
}

/** True when a connection exists for the transport AND has a stored key. */
export function isConfigured(connection: ProviderConnection | undefined): boolean {
  return Boolean(connection?.api_key_set);
}

/**
 * True when a connection is actually EXECUTABLE — a stored key whose latest
 * probe succeeded. This is the frontend mirror of the backend's admission
 * filter (`resolve_execution_credentials`), which skips any BYOK route whose
 * `last_test_status` is not `ok`. "We stored a key" is a weaker fact than
 * "the key works", and only the stronger one may offer an engine for a launch.
 */
export function isVerified(connection: ProviderConnection | undefined): boolean {
  return isConfigured(connection) && connection?.last_test_status === 'ok';
}

/**
 * Merge a logical-engine route into a connection's existing routes for a
 * create/update payload. Preserves other engines' routes on the same direct
 * connection and stamps the catalog default model for the added engine.
 */
export function mergeRoutePayload(
  existing: ProviderConnection | undefined,
  logical_engine: LogicalEngine,
): { logical_engine: LogicalEngine; is_default: boolean }[] {
  const routes = (existing?.routes ?? []).map((r) => ({
    logical_engine: r.logical_engine,
    is_default: r.is_default,
  }));
  if (!routes.some((r) => r.logical_engine === logical_engine)) {
    routes.push({ logical_engine, is_default: false });
  }
  return routes;
}

/** All approved (engine, transport, model) tuples, for the discovery selector. */
export type DiscoveryModelOption = {
  logical_engine: LogicalEngine;
  transport_provider: TransportProvider;
  transport_model: string;
  label: string;
};

/** Flatten the catalog into discovery-model options (plumbing-only, F8). */
export function discoveryModelOptions(
  catalog: ProviderCatalog | undefined,
): DiscoveryModelOption[] {
  return (catalog?.engines ?? []).flatMap((engine) =>
    engine.routes.map((route) => ({
      logical_engine: engine.logical_engine,
      transport_provider: route.transport_provider,
      transport_model: route.transport_model,
      label: `${ENGINE_LABELS[engine.logical_engine]} · ${TRANSPORT_LABELS[route.transport_provider]} · ${route.transport_model}`,
    })),
  );
}
