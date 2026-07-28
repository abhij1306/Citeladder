'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { CreditCard, ExternalLink } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog } from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { BILLING_CONFIRM_MAX_POLLS, BILLING_CONFIRM_POLL_MS, billingApi } from '@/lib/api/billing';
import { queryKeys } from '@/lib/api/query-keys';
import { useEntitlement } from '@/lib/billing/entitlement-context';

function money(amountMinor: number, currency: 'INR' | 'USD') {
  return new Intl.NumberFormat(currency === 'INR' ? 'en-IN' : 'en-US', {
    style: 'currency',
    currency,
  }).format(amountMinor / 100);
}

function message(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}

export function BillingSettings({ enabled = true }: Readonly<{ enabled?: boolean }>) {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { entitlement, isLoading: entitlementLoading } = useEntitlement();
  const [countryDraft, setCountryDraft] = useState('');
  const [confirming] = useState(() => searchParams.get('checkout') === 'return');
  const [confirmationPolls, setConfirmationPolls] = useState(0);
  const [cancelOpen, setCancelOpen] = useState(false);

  const summaryQuery = useQuery({
    queryKey: queryKeys.billing.me(),
    queryFn: ({ signal }) => billingApi.me({ signal }),
    enabled,
  });
  const summaryTier = summaryQuery.data?.tier_key;
  const refetchSummary = summaryQuery.refetch;
  const country = countryDraft || summaryQuery.data?.billing_country || '';
  const catalogQuery = useQuery({
    queryKey: queryKeys.billing.catalog(country || undefined),
    queryFn: ({ signal }) => billingApi.catalog(country || undefined, { signal }),
    enabled: enabled && summaryQuery.isSuccess,
  });

  useEffect(() => {
    if (!confirming) return;
    const params = new URLSearchParams(searchParams.toString());
    params.delete('checkout');
    const query = params.toString();
    window.history.replaceState(
      null,
      '',
      `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`,
    );
  }, [confirming, searchParams]);

  useEffect(() => {
    if (
      !enabled ||
      !confirming ||
      summaryTier === 'paid' ||
      confirmationPolls >= BILLING_CONFIRM_MAX_POLLS
    ) {
      return;
    }
    const timer = window.setTimeout(() => {
      void refetchSummary().finally(() => {
        setConfirmationPolls((count) => count + 1);
      });
    }, BILLING_CONFIRM_POLL_MS);
    return () => window.clearTimeout(timer);
  }, [confirmationPolls, confirming, enabled, refetchSummary, summaryTier]);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.billing.all });
  };
  const countryMutation = useMutation({
    mutationFn: () => billingApi.updateCountry(country.trim().toUpperCase()),
    onSuccess: refresh,
  });
  const checkoutMutation = useMutation({
    mutationFn: () => billingApi.checkout(globalThis.crypto.randomUUID()),
    onSuccess: ({ checkout_url }) => window.location.assign(checkout_url),
  });
  const cancelMutation = useMutation({
    mutationFn: () => billingApi.cancel(),
    onSuccess: async () => {
      setCancelOpen(false);
      await refresh();
    },
  });

  if (!enabled || summaryQuery.isLoading) {
    return (
      <Card>
        <CardContent className="grid gap-3">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-20 w-full" />
        </CardContent>
      </Card>
    );
  }
  if (summaryQuery.isError || !summaryQuery.data) {
    return <Alert tone="danger">Could not load billing. Check your connection and retry.</Alert>;
  }

  const summary = summaryQuery.data;
  const paidPlan = catalogQuery.data?.plans.find((plan) => plan.tier_key === 'paid');
  const price = paidPlan?.price;
  const effectiveTier = entitlement?.tier_key ?? summary.tier_key;
  const confirmationTimedOut =
    confirming && summary.tier_key !== 'paid' && confirmationPolls >= BILLING_CONFIRM_MAX_POLLS;

  return (
    <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
      {confirming ? (
        <Alert
          tone={summary.tier_key === 'paid' ? 'success' : confirmationTimedOut ? 'warning' : 'info'}
        >
          {summary.tier_key === 'paid'
            ? 'Payment confirmed. Paid capabilities are active.'
            : confirmationTimedOut
              ? 'Payment is still confirming — your plan has not changed.'
              : 'Confirming payment — your plan will update here after verification completes.'}
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Current plan</CardTitle>
          <CardDescription>
            The active workspace inherits its sponsor’s entitlement.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-foreground text-heading-sm capitalize">{effectiveTier}</p>
              <p className="text-muted mt-1 text-xs">
                {summary.subscription_status
                  ? `Razorpay subscription: ${summary.subscription_status.replaceAll('_', ' ')}`
                  : 'No Razorpay subscription'}
              </p>
            </div>
            <Badge variant="status" value={effectiveTier === 'paid' ? 'success' : 'info'}>
              {effectiveTier === 'paid' ? 'Paid' : 'Free'}
            </Badge>
          </div>
          {entitlementLoading ? (
            <p className="text-muted text-xs">Loading workspace entitlement…</p>
          ) : null}
          {summary.current_period_end ? (
            <p className="text-secondary text-sm">
              {summary.cancel_at_period_end ? 'Access scheduled to end' : 'Current period ends'}{' '}
              {new Date(summary.current_period_end).toLocaleDateString()}.
            </p>
          ) : null}
          {summary.subscription_status && !summary.cancel_at_period_end ? (
            <Button
              variant="secondary"
              disabled={cancelMutation.isPending}
              onClick={() => setCancelOpen(true)}
            >
              {cancelMutation.isPending ? 'Scheduling cancellation…' : 'Cancel at period end'}
            </Button>
          ) : null}
          {cancelMutation.isError ? (
            <Alert tone="danger">{message(cancelMutation.error)}</Alert>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Paid monthly</CardTitle>
          <CardDescription>
            India uses INR with GST added. Other supported countries use USD; your card issuer may
            convert the charge.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {catalogQuery.isError ? (
            <Alert tone="danger">
              Could not load the regional price catalog. Check your connection and retry.
            </Alert>
          ) : catalogQuery.isLoading ? (
            <Skeleton className="h-16 w-full" />
          ) : price && price.total_amount_minor > 0 ? (
            <div>
              <p className="text-foreground text-xl font-semibold">
                {money(price.base_amount_minor, price.currency)}
                <span className="text-muted ml-1 text-sm font-normal">/ month</span>
              </p>
              {price.tax_label ? (
                <p className="text-muted mt-1 text-xs">
                  {price.tax_label}; checkout total{' '}
                  {money(price.total_amount_minor, price.currency)}.
                </p>
              ) : null}
            </div>
          ) : (
            <Alert tone="info">
              The INR catalog amount will appear after the approved USD/INR provisioning rate is
              configured. The published international anchor remains $49/month before tax.
            </Alert>
          )}

          <label className="grid gap-1.5 text-sm">
            <span className="text-secondary font-medium">Billing country</span>
            <input
              value={country}
              onChange={(event) => setCountryDraft(event.target.value.toUpperCase().slice(0, 2))}
              placeholder="IN"
              aria-describedby="billing-country-help"
              className="border-border bg-background focus-ring h-10 rounded-md border px-3 uppercase outline-none"
            />
            <span id="billing-country-help" className="text-muted text-xs">
              Two-letter ISO code. This server-owned profile selects the fixed INR or USD plan; it
              cannot be overridden at checkout.
            </span>
          </label>
          <Button
            variant="secondary"
            disabled={country.length !== 2 || countryMutation.isPending}
            onClick={() => countryMutation.mutate()}
          >
            {countryMutation.isPending ? 'Saving…' : 'Save billing country'}
          </Button>
          {countryMutation.isError ? (
            <Alert tone="danger">{message(countryMutation.error)}</Alert>
          ) : null}

          {summary.tier_key === 'free' ? (
            <Button
              disabled={!summary.can_checkout || checkoutMutation.isPending}
              onClick={() => checkoutMutation.mutate()}
            >
              <CreditCard className="size-4" aria-hidden />
              {checkoutMutation.isPending ? 'Opening Razorpay…' : 'Upgrade with Razorpay'}
            </Button>
          ) : null}
          {!summary.can_checkout && summary.tier_key === 'free' ? (
            <Alert tone="info">
              {summary.checkout_block_reason === 'billing_country_required'
                ? 'Save your billing country to see the available checkout route.'
                : 'Live checkout is not enabled yet — your Free plan remains active.'}
            </Alert>
          ) : null}
          {checkoutMutation.isError ? (
            <Alert tone="danger">{message(checkoutMutation.error)}</Alert>
          ) : null}

          <Button asChild variant="secondary">
            <Link href="/demo">
              Enterprise options <ExternalLink className="size-4" aria-hidden />
            </Link>
          </Button>
        </CardContent>
      </Card>

      <Dialog
        open={cancelOpen}
        onOpenChange={(open) => {
          if (!cancelMutation.isPending) setCancelOpen(open);
        }}
        title="Cancel Paid plan"
        description="Cancellation takes effect at the end of the current billing period."
        footer={
          <>
            <Button
              variant="secondary"
              disabled={cancelMutation.isPending}
              onClick={() => setCancelOpen(false)}
            >
              Keep Paid
            </Button>
            <Button
              variant="destructive"
              disabled={cancelMutation.isPending}
              onClick={() => cancelMutation.mutate()}
            >
              {cancelMutation.isPending ? 'Scheduling cancellation…' : 'Cancel at period end'}
            </Button>
          </>
        }
      >
        <p className="text-secondary text-sm">
          Paid capabilities remain available through the verified paid-through date. Completed
          audits and evidence are not deleted when the plan ends.
        </p>
        {cancelMutation.isError ? (
          <Alert tone="danger">{message(cancelMutation.error)}</Alert>
        ) : null}
      </Dialog>
    </div>
  );
}
