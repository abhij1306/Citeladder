'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { CreditCard, ExternalLink } from 'lucide-react';
import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { UsageMeters } from '@/components/billing/usage-meters';
import {
  billingApi,
  createIdempotencyKey,
  type BillingEntitlement,
  type CatalogPlan,
  type SelfServePlanKey,
} from '@/lib/api/billing';
import { queryKeys } from '@/lib/api/query-keys';
import { useEntitlement } from '@/lib/billing/entitlement-context';
import { hardNavigate } from '@/lib/navigation/hard-navigate';
import {
  catalogPlanByKey,
  checkoutSelection,
  formatMoney,
  headlinePrice,
} from '@/lib/billing/catalog';

function message(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}

type BillingCheckout = { pending: boolean; error: unknown; start: (key: SelfServePlanKey) => void };
type BillingCancellation = { pending: boolean; error: unknown; confirm: () => void };

type BillingState = {
  country: string;
  cancelOpen: boolean;
  setCountry: (country: string) => void;
  setCancelOpen: (open: boolean) => void;
};

function useBillingState(): BillingState {
  const [country, setCountry] = useState('');
  const [cancelOpen, setCancelOpen] = useState(false);
  return { country, cancelOpen, setCountry, setCancelOpen };
}

/** Account plan orchestration. Usage rendering lives in `UsageMeters`. */
export function BillingSettings({ enabled = true }: Readonly<{ enabled?: boolean }>) {
  const queryClient = useQueryClient();
  const { entitlement, isLoading: entitlementLoading } = useEntitlement();
  const state = useBillingState();
  const catalogQuery = useQuery({
    queryKey: queryKeys.billing.catalog(state.country || undefined),
    queryFn: ({ signal }) => billingApi.catalog(state.country || undefined, { signal }),
    enabled,
    placeholderData: keepPreviousData,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.billing.all });
  const checkoutMutation = useMutation({
    mutationFn: (catalogKey: SelfServePlanKey) =>
      billingApi.createSubscription(
        { catalog_key: catalogKey, credential_mode: 'byok', country_code: state.country },
        createIdempotencyKey(),
      ),
    onSuccess: async (activation) => {
      if (activation.checkout_url) return hardNavigate(activation.checkout_url);
      await refresh();
    },
  });
  const cancelMutation = useMutation({
    mutationFn: () => billingApi.cancelSubscription(),
    onSuccess: async () => {
      state.setCancelOpen(false);
      await refresh();
    },
  });

  if (!enabled || entitlementLoading) return <BillingSkeleton />;

  return (
    <BillingContent
      enabled={enabled}
      entitlement={entitlement}
      catalog={catalogQuery.data ?? null}
      catalogLoading={catalogQuery.isLoading}
      catalogError={catalogQuery.isError}
      state={state}
      checkout={{
        pending: checkoutMutation.isPending,
        error: checkoutMutation.isError ? checkoutMutation.error : null,
        start: (key) => checkoutMutation.mutate(key),
      }}
      cancellation={{
        pending: cancelMutation.isPending,
        error: cancelMutation.isError ? cancelMutation.error : null,
        confirm: () => cancelMutation.mutate(),
      }}
    />
  );
}

function BillingSkeleton() {
  return (
    <div className="bg-panel shadow-card border-border-subtle grid gap-3 rounded-md border p-[var(--card-padding)]">
      <Skeleton className="h-6 w-40" />
      <Skeleton className="h-20 w-full" />
    </div>
  );
}

function BillingContent({
  enabled,
  entitlement,
  catalog,
  catalogLoading,
  catalogError,
  state,
  checkout,
  cancellation,
}: Readonly<{
  enabled: boolean;
  entitlement: BillingEntitlement | null;
  catalog: Awaited<ReturnType<typeof billingApi.catalog>> | null;
  catalogLoading: boolean;
  catalogError: boolean;
  state: BillingState;
  checkout: BillingCheckout;
  cancellation: BillingCancellation;
}>) {
  const subscription = entitlement?.subscription ?? null;
  const currentPlan =
    subscription && catalog ? (catalogPlanByKey(catalog, subscription.catalog_key) ?? null) : null;

  return (
    <div className="grid gap-[var(--workspace-gap)]">
      <CurrentPlan
        entitlement={entitlement}
        currentPlan={currentPlan}
        cancelPending={cancellation.pending}
        cancelError={cancellation.error}
        onCancel={() => state.setCancelOpen(true)}
      />
      <div className="grid gap-[var(--workspace-gap)] lg:grid-cols-12 lg:items-start">
        <PlanCatalog
          catalog={catalog}
          loading={catalogLoading}
          error={catalogError}
          country={state.country}
          setCountry={state.setCountry}
          pending={checkout.pending}
          checkoutError={checkout.error}
          onCheckout={checkout.start}
        />
        <div className="lg:col-span-5">
          <UsageMeters enabled={enabled} />
        </div>
      </div>
      <CancelDialog cancellation={cancellation} state={state} />
    </div>
  );
}

function CurrentPlan({
  entitlement,
  currentPlan,
  cancelPending,
  cancelError,
  onCancel,
}: Readonly<{
  entitlement: BillingEntitlement | null;
  currentPlan: CatalogPlan | null;
  cancelPending: boolean;
  cancelError: unknown;
  onCancel: () => void;
}>) {
  const subscription = entitlement?.subscription ?? null;
  const periodEnd = subscription?.current_period_end;
  return (
    <div className="bg-panel shadow-card border-border-subtle rounded-md border p-[var(--card-padding)]">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-muted text-2xs font-semibold">Current plan</p>
          <div className="mt-1 flex items-center gap-2.5">
            <p className="text-foreground text-heading-sm font-semibold">
              {currentPlan?.name ?? subscription?.catalog_key ?? 'No active plan'}
            </p>
            <Badge variant="status" value={subscription ? 'success' : 'info'}>
              {subscription ? 'Active' : 'None'}
            </Badge>
          </div>
          <SubscriptionDetail subscription={subscription} periodEnd={periodEnd} />
        </div>
        {subscription && !subscription.cancel_at_period_end ? (
          <Button variant="secondary" size="sm" disabled={cancelPending} onClick={onCancel}>
            {cancelPending ? 'Scheduling cancellation…' : 'Cancel at period end'}
          </Button>
        ) : null}
      </div>
      {entitlement === null ? (
        <div className="mt-4">
          <Alert tone="warning">
            Your entitlement could not be resolved. No paid capability is active until it does.
          </Alert>
        </div>
      ) : null}
      {cancelError ? (
        <div className="mt-4">
          <Alert tone="danger">{message(cancelError)}</Alert>
        </div>
      ) : null}
    </div>
  );
}

function PlanCatalog({
  catalog,
  loading,
  error,
  country,
  setCountry,
  pending,
  checkoutError,
  onCheckout,
}: Readonly<{
  catalog: Awaited<ReturnType<typeof billingApi.catalog>> | null;
  loading: boolean;
  error: boolean;
  country: string;
  setCountry: (country: string) => void;
  pending: boolean;
  checkoutError: unknown;
  onCheckout: (key: SelfServePlanKey) => void;
}>) {
  return (
    <div className="bg-panel shadow-card border-border-subtle grid gap-4 rounded-md border p-[var(--card-padding)] lg:col-span-7">
      <div>
        <h2 className="text-foreground text-sm font-semibold tracking-tight">Change plan</h2>
        <p className="text-muted mt-0.5 text-xs">
          Prices are resolved by the server for your billing country. Audits run on your own
          provider keys, billed by those providers directly.
        </p>
      </div>
      {error ? (
        <Alert tone="danger">
          Could not load the plan catalog. Check your connection and retry.
        </Alert>
      ) : loading || !catalog ? (
        <Skeleton className="h-24 w-full" />
      ) : (
        <div className="grid gap-3">
          <CountryInput country={country} setCountry={setCountry} />
          <div className="grid gap-2.5">
            {catalog.plans.map((plan) => (
              <PlanRow
                key={plan.key}
                plan={plan}
                currencyMinorUnits={catalog.currency_minor_units}
                country={country}
                pending={pending}
                onCheckout={onCheckout}
              />
            ))}
          </div>
          {checkoutError ? <Alert tone="danger">{message(checkoutError)}</Alert> : null}
        </div>
      )}
    </div>
  );
}

function CountryInput({
  country,
  setCountry,
}: Readonly<{ country: string; setCountry: (country: string) => void }>) {
  return (
    <div className="bg-background-alt border-border-subtle flex flex-col justify-between gap-2.5 rounded-md border p-3 sm:flex-row sm:items-center">
      <div className="min-w-0">
        <label htmlFor="billing-country-input" className="text-secondary block text-xs font-medium">
          Billing country
        </label>
        <span id="billing-country-help" className="text-muted text-2xs block">
          Two-letter ISO code. The server resolves currency, tax and the exact amount from it.
        </span>
      </div>
      <input
        id="billing-country-input"
        value={country}
        onChange={(event) => setCountry(event.target.value.toUpperCase().slice(0, 2))}
        placeholder="US"
        aria-describedby="billing-country-help"
        className="border-border bg-background focus-ring h-8 w-20 rounded border px-2.5 text-center font-mono text-xs font-semibold uppercase outline-none"
      />
    </div>
  );
}

function SubscriptionDetail({
  subscription,
  periodEnd,
}: Readonly<{
  subscription: BillingEntitlement['subscription'] | null;
  periodEnd: string | null | undefined;
}>) {
  if (!subscription) return <p className="text-muted mt-1 text-xs">No active subscription</p>;
  return (
    <p className="text-muted mt-1 text-xs">
      Subscription: {subscription.status.replaceAll('_', ' ')}
      {periodEnd ? (
        <>
          {' · '}
          {subscription.cancel_at_period_end ? 'Access scheduled to end ' : 'Current period ends '}
          {new Date(periodEnd).toLocaleDateString('en-US', {
            dateStyle: 'medium',
            timeZone: 'UTC',
          })}
          .
        </>
      ) : null}
    </p>
  );
}

function PlanRow({
  plan,
  currencyMinorUnits,
  country,
  pending,
  onCheckout,
}: Readonly<{
  plan: CatalogPlan;
  currencyMinorUnits: number;
  country: string;
  pending: boolean;
  onCheckout: (key: SelfServePlanKey) => void;
}>) {
  const { priceLabel, selection, canCheckout } = planCheckoutState(
    plan,
    currencyMinorUnits,
    country,
    pending,
  );
  return (
    <div
      className="bg-background-alt border-border-subtle flex flex-col justify-between gap-3 rounded-md border p-3.5 sm:flex-row sm:items-center"
      data-tier={plan.key}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-foreground text-sm font-semibold">{plan.name}</span>
          <span className="text-muted font-mono text-xs font-medium">{priceLabel}</span>
        </div>
        {plan.description ? <p className="text-muted mt-0.5 text-xs">{plan.description}</p> : null}
        {!selection.ok && !plan.contact_only && selection.reason ? (
          <p className="text-muted text-2xs mt-0.5">{selection.reason}</p>
        ) : null}
      </div>
      <div className="shrink-0">
        {plan.contact_only ? (
          <Button asChild variant="secondary" size="sm">
            <Link href={plan.contact_url ?? '/demo'}>
              Contact sales <ExternalLink className="size-3.5" aria-hidden />
            </Link>
          </Button>
        ) : (
          <Button
            size="sm"
            disabled={!canCheckout}
            onClick={() => selection.ok && onCheckout(selection.catalog_key)}
          >
            <CreditCard className="size-3.5" aria-hidden />
            {pending ? 'Opening checkout…' : `Choose ${plan.name}`}
          </Button>
        )}
      </div>
    </div>
  );
}

function planCheckoutState(
  plan: CatalogPlan,
  currencyMinorUnits: number,
  country: string,
  pending: boolean,
) {
  const price = headlinePrice(plan, 'byok');
  const selection = checkoutSelection(plan, 'byok');
  const priceLabel =
    price.kind === 'price'
      ? `${formatMoney(price.money, currencyMinorUnits)} / month`
      : price.kind === 'contact'
        ? 'Contact us'
        : 'Not yet priced';
  return { priceLabel, selection, canCheckout: selection.ok && country.length === 2 && !pending };
}

function CancelDialog({
  cancellation,
  state,
}: Readonly<{ cancellation: BillingCancellation; state: BillingState }>) {
  return (
    <Dialog
      open={state.cancelOpen}
      onOpenChange={(open) => {
        if (!cancellation.pending) state.setCancelOpen(open);
      }}
      title="Cancel subscription"
      description="Cancellation takes effect at the end of the current billing period."
      footer={
        <>
          <Button
            variant="secondary"
            disabled={cancellation.pending}
            onClick={() => state.setCancelOpen(false)}
          >
            Keep plan
          </Button>
          <Button
            variant="destructive"
            disabled={cancellation.pending}
            onClick={cancellation.confirm}
          >
            {cancellation.pending ? 'Scheduling cancellation…' : 'Cancel at period end'}
          </Button>
        </>
      }
    >
      <p className="text-secondary text-sm">
        Your current period runs to its end and no next bundle is issued. Completed audits and
        evidence are never deleted when a plan ends.
      </p>
      {cancellation.error ? <Alert tone="danger">{message(cancellation.error)}</Alert> : null}
    </Dialog>
  );
}
