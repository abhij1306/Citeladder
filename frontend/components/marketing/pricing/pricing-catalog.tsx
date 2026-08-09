'use client';

import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { Switch } from '@/components/ui/switch';
import {
  billingApi,
  createIdempotencyKey,
  type CatalogAddon,
  type CatalogPlan,
  type CatalogTopup,
} from '@/lib/api/billing';
import { authApi } from '@/lib/api/auth';
import { queryKeys } from '@/lib/api/query-keys';
import { checkoutSelection, isPurchasable, isSelfServeKey } from '@/lib/billing/catalog';
import {
  clearPendingIntent,
  readPendingIntent,
  writePendingIntent,
  type PendingIntentKind,
  type PendingPricingIntentV1,
} from '@/lib/billing/pending-pricing-intent';
import { PRICING_RESUME_QUERY_PARAM, PRICING_RETURN_PATH } from '@/lib/config/billing';
import { hardNavigate } from '@/lib/navigation/hard-navigate';
import { BYOK_DISCLOSURE, BYOK_SWITCH_LABEL } from '@/lib/marketing-content/pricing';

import { Section, SectionHeader } from '../primitives/section';
import { CatalogPurchases } from './catalog-purchases';
import { PricingComparison } from './pricing-comparison';
import { PricingTierCard } from './pricing-tier-card';
import { useByokPricing } from './use-byok-pricing';

const STALE_INTENT_MESSAGE = 'That pricing option is no longer available. Please choose again.';

/**
 * Build the breadcrumb for one selection. Module scope, not the component
 * body: it reads the clock and mints a key, so it belongs to the click that
 * calls it rather than to a render.
 */
function intentFor(
  kind: PendingIntentKind,
  catalogKey: string,
  quantity: number,
  byok: boolean,
): PendingPricingIntentV1 {
  return {
    version: 1,
    kind,
    catalog_key: catalogKey,
    quantity,
    byok,
    country_code: null,
    idempotency_key: createIdempotencyKey(),
    return_path: PRICING_RETURN_PATH,
    created_at_ms: Date.now(),
  };
}

/**
 * The catalog-backed pricing island.
 *
 * The page around it stays a sync server component; this owns every network
 * read, the credential-mode state shared by all cards, and the anonymous
 * capture-and-resume flow.
 *
 * Capture-and-resume exists because an anonymous visitor must see real,
 * clickable controls without a billing request ever leaving the browser
 * unauthenticated. The click stores an untrusted breadcrumb, routes to auth,
 * and on return the selection is REVALIDATED against the live catalog before
 * any mutation — stored prices and availability are never replayed.
 */
export function PricingCatalog() {
  const { byok, setByok } = useByokPricing();
  const mode = byok ? 'byok' : 'funded';
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  /**
   * Is anyone signed in? This is a PUBLIC page, so there is no SessionGuard
   * above it and a 401 here is the ordinary anonymous case, not an error —
   * hence no retries and a settled-but-null result. It gates only whether a
   * click captures an intent or issues a request; the backend still authorizes
   * every mutation itself.
   */
  const sessionQuery = useQuery({
    queryKey: queryKeys.auth.me(),
    queryFn: ({ signal }) => authApi.me({ signal }).catch(() => null),
    retry: false,
    staleTime: 60_000,
  });
  const isAuthenticated = Boolean(sessionQuery.data);

  const catalogQuery = useQuery({
    queryKey: queryKeys.billing.catalog(),
    queryFn: ({ signal }) => billingApi.catalog(undefined, { signal }),
  });
  const catalog = catalogQuery.data ?? null;

  const activation = useMutation({
    onMutate: (intent: PendingPricingIntentV1) => setPendingKey(intent.catalog_key),
    mutationFn: async (intent: PendingPricingIntentV1) => {
      if (intent.kind === 'addon') {
        return billingApi.activateAddon(
          intent.catalog_key,
          intent.quantity,
          intent.idempotency_key,
        );
      }
      if (intent.kind === 'topup') {
        return billingApi.purchaseTopup(
          intent.catalog_key,
          intent.quantity,
          intent.idempotency_key,
        );
      }
      if (!isSelfServeKey(intent.catalog_key)) {
        throw new Error(STALE_INTENT_MESSAGE);
      }
      return billingApi.createSubscription(
        {
          catalog_key: intent.catalog_key,
          credential_mode: intent.byok ? 'byok' : 'funded',
          country_code: intent.country_code ?? '',
        },
        intent.idempotency_key,
      );
    },
    onSuccess: (result) => {
      // Accepted (pending or activated) and terminal failures both settle the
      // intent — only an auth/network failure is worth retaining.
      clearPendingIntent();
      setPendingKey(null);
      if (result.checkout_url) hardNavigate(result.checkout_url);
    },
    onError: () => setPendingKey(null),
  });

  const runOrCapture = (intent: PendingPricingIntentV1) => {
    setNotice(null);
    // An anonymous visitor never issues a billing POST. The breadcrumb is
    // written first so a full-page navigation to auth cannot lose it.
    if (!isAuthenticated) {
      writePendingIntent(intent);
      hardNavigate('/login');
      return;
    }
    activation.mutate(intent);
  };

  /**
   * Resume after authentication.
   *
   * Modelled as ONE mutation that can fail rather than as effect-driven
   * branching: revalidation, the purchase, and the "choose again" message are
   * three outcomes of a single operation, so the effect only starts it and
   * every state change lands in a mutation callback.
   *
   * Revalidation is the point of the whole flow — a stored key that vanished,
   * changed availability, or whose quantity no longer fits its bounds is
   * rejected before any request is made.
   */
  const resume = useMutation({
    mutationFn: async () => {
      const stored = readPendingIntent();
      if (!stored || !catalog || !isStillValid(stored, catalog)) {
        clearPendingIntent();
        throw new Error(STALE_INTENT_MESSAGE);
      }
      return activation.mutateAsync(stored);
    },
    onError: () => setNotice(STALE_INTENT_MESSAGE),
  });

  // `mutate` is referentially stable across renders, so it is a safe dep and
  // needs no ref to dodge the lint.
  const startResume = resume.mutate;
  useEffect(() => {
    if (!catalog || !isAuthenticated) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get(PRICING_RESUME_QUERY_PARAM) !== '1') return;

    // Consume the flag before starting, so a re-render cannot resume twice.
    params.delete(PRICING_RESUME_QUERY_PARAM);
    const query = params.toString();
    window.history.replaceState(
      null,
      '',
      `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`,
    );
    startResume();
  }, [catalog, isAuthenticated, startResume]);

  return (
    <>
      <Section tone="paper" rhythm="tight" aria-label="Plans">
        <div className="mb-8 flex flex-wrap items-center gap-4">
          <Switch
            checked={byok}
            onCheckedChange={setByok}
            label={BYOK_SWITCH_LABEL}
            describedBy="byok-disclosure"
          />
          <span className="text-foreground text-sm font-medium">{BYOK_SWITCH_LABEL}</span>
          <p id="byok-disclosure" className="website-body text-muted max-w-[70ch] basis-full">
            {BYOK_DISCLOSURE}
          </p>
        </div>

        {notice && (
          <p role="status" className="website-body text-warning-text mb-8">
            {notice}
          </p>
        )}
        {activation.isError && (
          <p role="status" className="website-body text-warning-text mb-8">
            {activation.error instanceof Error
              ? activation.error.message
              : 'That purchase could not be started. Please try again.'}
          </p>
        )}

        {catalogQuery.isError ? (
          <CatalogError onRetry={() => void catalogQuery.refetch()} />
        ) : !catalog ? (
          <LoadingCards />
        ) : (
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
            {catalog.plans.map((plan) => (
              <PricingTierCard
                key={plan.key}
                plan={plan}
                catalog={catalog}
                mode={mode}
                pending={pendingKey === plan.key}
                onCheckout={(selected: CatalogPlan) => {
                  const selection = checkoutSelection(selected, mode);
                  if (!selection.ok) return;
                  runOrCapture(intentFor('checkout', selection.catalog_key, 1, byok));
                }}
              />
            ))}
          </div>
        )}
      </Section>

      <Section tone="sunken" rhythm="tight" aria-label="Plan comparison">
        <SectionHeader
          eyebrow="Compare"
          title="Side by side."
          lead="Every cell is a limit the platform enforces."
          headingId="pricing-compare-title"
        />
        {catalog ? <PricingComparison catalog={catalog} /> : <LoadingShell />}
      </Section>

      {catalog && (catalog.addons.length > 0 || catalog.topups.length > 0) && (
        <Section tone="paper" rhythm="tight" aria-label="Add-ons and top-ups">
          <CatalogPurchases
            catalog={catalog}
            pendingKey={pendingKey}
            onActivateAddon={(addon: CatalogAddon) => {
              if (!isPurchasable(addon)) return;
              runOrCapture(intentFor('addon', addon.key, addon.quantity_min, byok));
            }}
            onPurchaseTopup={(topup: CatalogTopup) => {
              if (!isPurchasable(topup)) return;
              runOrCapture(intentFor('topup', topup.key, topup.quantity_min, byok));
            }}
          />
        </Section>
      )}
    </>
  );
}

/**
 * Revalidate a stored intent against the live catalog. Anything the catalog no
 * longer supports — an unknown key, a withdrawn item, a quantity outside the
 * current bounds — is rejected before any request is made.
 */
function isStillValid(
  intent: PendingPricingIntentV1,
  catalog: NonNullable<
    ReturnType<typeof useQuery<Awaited<ReturnType<typeof billingApi.catalog>>>>['data']
  >,
): boolean {
  if (intent.kind === 'checkout') {
    const plan = catalog.plans.find((entry) => entry.key === intent.catalog_key);
    if (!plan) return false;
    const mode = intent.byok ? 'byok' : 'funded';
    return checkoutSelection(plan, mode).ok && intent.quantity === 1;
  }
  const pool = intent.kind === 'addon' ? catalog.addons : catalog.topups;
  const entry = pool.find((candidate) => candidate.key === intent.catalog_key);
  if (!entry) return false;
  if (!isPurchasable(entry)) return false;
  return intent.quantity >= entry.quantity_min && intent.quantity <= entry.quantity_max;
}

function LoadingCards() {
  return (
    <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4" aria-busy="true">
      {[0, 1, 2, 3].map((index) => (
        <div
          key={index}
          data-loading-card
          className="bg-panel shadow-card h-80 animate-pulse rounded-lg"
        />
      ))}
      <p className="sr-only">Loading plans…</p>
    </div>
  );
}

function LoadingShell() {
  return <div aria-busy="true" className="bg-panel h-48 animate-pulse rounded-md" />;
}

function CatalogError({ onRetry }: Readonly<{ onRetry: () => void }>) {
  return (
    <div className="border-border-subtle grid gap-4 rounded-lg border border-dashed p-10 text-center">
      <p className="website-body text-muted">
        Plans could not be loaded, so no price is shown. Check your connection and retry.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="border-border-subtle text-foreground focus-ring mx-auto inline-flex h-10 items-center rounded-md border px-5 text-sm font-medium"
      >
        Retry
      </button>
    </div>
  );
}
