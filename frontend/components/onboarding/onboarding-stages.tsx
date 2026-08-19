import Link from 'next/link';
import { Controller, type UseFormReturn } from 'react-hook-form';

import { ActivityProgress } from '@/components/ui/activity-progress';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { MarketSelect } from '@/components/ui/market-select';
import { COUNTRY_OPTIONS, LANGUAGE_OPTIONS } from '@/lib/setup/markets';
import { discoveryActivity } from '@/lib/onboarding/discovery-activity';
import { onboardingErrorMessage, type BrandStepValues } from '@/lib/onboarding/forms';
import { hasConfirmedIcp, IcpConfirmation } from './icp-confirmation';
import { ReviewStep } from './review-step';

const MARKET_OPTIONS = [{ value: 'GLOBAL', label: 'Global' }, ...COUNTRY_OPTIONS];

export function BrandStage({
  form,
  isAdditional,
  onSubmit,
}: Readonly<{
  form: UseFormReturn<BrandStepValues>;
  isAdditional: boolean;
  onSubmit: () => void;
}>) {
  return (
    <form noValidate onSubmit={onSubmit} className="space-y-6">
      <div className="space-y-1">
        <h1 className="website-feature-heading text-foreground">
          {isAdditional ? 'Add a project' : "Let's get started"}
        </h1>
        <p className="website-body text-muted">
          We&apos;ll review your website, suggest comparable brands, and prepare balanced questions.
        </p>
      </div>
      <div className="grid items-start gap-x-6 gap-y-5 sm:grid-cols-2">
        <Field label="Brand name" required error={form.formState.errors.brand_name?.message}>
          {(props) => (
            <Input {...props} {...form.register('brand_name')} placeholder="Acme" size="lg" />
          )}
        </Field>
        <Field label="Website" required error={form.formState.errors.website_url?.message}>
          {(props) => (
            <Input
              {...props}
              {...form.register('website_url')}
              placeholder="acme.com"
              inputMode="url"
              size="lg"
            />
          )}
        </Field>
        <Field label="Primary market" error={form.formState.errors.primary_market?.message}>
          {(props) => (
            <Controller
              control={form.control}
              name="primary_market"
              render={({ field }) => (
                <MarketSelect
                  {...props}
                  ariaLabel="Primary market"
                  value={field.value}
                  onChange={field.onChange}
                  onBlur={field.onBlur}
                  options={MARKET_OPTIONS}
                />
              )}
            />
          )}
        </Field>
        <Field label="Language" error={form.formState.errors.language_code?.message}>
          {(props) => (
            <Controller
              control={form.control}
              name="language_code"
              render={({ field }) => (
                <MarketSelect
                  {...props}
                  ariaLabel="Language"
                  value={field.value}
                  onChange={field.onChange}
                  onBlur={field.onBlur}
                  options={LANGUAGE_OPTIONS}
                />
              )}
            />
          )}
        </Field>
      </div>
      <div className="flex items-center gap-3 pt-2">
        <Button type="submit" size="lg" className="text-sm font-medium">
          Continue
        </Button>
        {isAdditional ? (
          <Button asChild variant="ghost" size="lg">
            <Link href="/projects">Cancel</Link>
          </Button>
        ) : null}
      </div>
    </form>
  );
}

export function DiscoveryStage({
  brandName,
  discovery,
  onEdit,
  onReview,
}: Readonly<{
  brandName: string | undefined;
  discovery: {
    discovery: ReturnType<
      typeof import('@/lib/onboarding/use-brand-discovery').useBrandDiscovery
    >['discovery'];
    error: Error | null;
    isRunning: boolean;
    retry: () => void;
  };
  onEdit: () => void;
  onReview: () => void;
}>) {
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h1 className="website-feature-heading text-foreground">Finding what to track</h1>
        <p className="website-body text-muted">
          We&apos;re learning about {brandName || 'your brand'} and preparing useful questions. You
          can review everything before the project is created.
        </p>
      </div>
      <div className="border-border-subtle bg-well/40 rounded-sm border p-3.5">
        <ActivityProgress
          label="Discovering your brand"
          steps={discoveryActivity(discovery.discovery)}
          animateCompletion
        />
      </div>
      {(discovery.discovery?.warnings ?? []).map((warning) => (
        <Alert key={warning} tone="warning" className="website-body px-3 py-2.5">
          {warningMessage(warning)}
        </Alert>
      ))}
      {discovery.discovery?.status === 'failed' ? (
        <Alert tone="danger">
          <div className="flex items-center justify-between gap-3">
            <span>
              {discovery.discovery.error_code === 'invalid_url'
                ? 'The website address is invalid. Go back and correct it.'
                : 'We could not confirm that this website exists. Check the address and try again.'}
            </span>
            <Button size="sm" variant="ghost" onClick={onEdit}>
              Edit website
            </Button>
          </div>
        </Alert>
      ) : null}
      {discovery.error ? (
        <Alert tone="danger">
          <div className="flex items-center justify-between gap-3">
            <span>{onboardingErrorMessage(discovery.error)}</span>
            <Button
              size="sm"
              variant="ghost"
              onClick={discovery.retry}
              disabled={discovery.isRunning}
            >
              Retry
            </Button>
          </div>
        </Alert>
      ) : null}
      <div className="flex items-center gap-3 pt-2">
        <Button
          size="lg"
          onClick={onReview}
          disabled={
            discovery.isRunning || !discovery.discovery || discovery.discovery.status !== 'ready'
          }
          className="text-sm font-medium"
        >
          {discovery.isRunning ? 'Searching…' : 'Review'}
        </Button>
        <Button variant="ghost" size="lg" onClick={onEdit}>
          Back
        </Button>
      </div>
    </div>
  );
}

export function ReviewStage({
  flow,
}: Readonly<{ flow: ReturnType<typeof import('./onboarding-flow').useOnboardingFlow> }>) {
  const {
    catalog,
    competitors,
    complete,
    domains,
    hasSelectedDomain,
    maximumCompetitors,
    profile,
    setCompetitors,
    setProfile,
    setStep,
    toggle,
  } = flow;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h1 className="website-feature-heading text-foreground">Does this look right?</h1>
        <p className="website-label text-muted">
          Deselect anything you don&apos;t want — you can change all of it after setup.
        </p>
      </div>
      <div className="border-border-subtle bg-panel divide-border-subtle grid divide-y rounded-sm border lg:grid-cols-2 lg:divide-x lg:divide-y-0">
        <div className="divide-border-subtle divide-y px-4 py-3">
          {profile ? <IcpConfirmation profile={profile} onChange={setProfile} /> : null}
        </div>
        <ReviewStep
          domains={domains}
          competitors={competitors}
          onToggleDomain={toggle(flow.setDomains)}
          onToggleCompetitor={(index) =>
            toggleCompetitor(index, setCompetitors, maximumCompetitors)
          }
          onEditCompetitorDomain={(index, domain) =>
            editCompetitorDomain(index, domain, setCompetitors)
          }
          onAddCompetitor={() => addCompetitor(setCompetitors, maximumCompetitors)}
          maximumCompetitors={maximumCompetitors}
        />
      </div>
      {catalog.isError ? (
        <Alert tone="warning">
          <div className="flex items-center justify-between gap-3">
            <span>We could not load the competitor limit.</span>
            <Button size="sm" variant="ghost" onClick={() => catalog.refetch()}>
              Try again
            </Button>
          </div>
        </Alert>
      ) : null}
      {complete.isError ? (
        <Alert tone="danger">{onboardingErrorMessage(complete.error)}</Alert>
      ) : null}
      {!hasSelectedDomain ? (
        <Alert tone="warning">Keep at least one website address selected.</Alert>
      ) : null}
      {!hasConfirmedIcp(profile) ? (
        <Alert tone="warning">Choose or describe what you sell.</Alert>
      ) : null}
      <div className="-mt-1 flex items-center gap-3 pt-1">
        <Button
          size="lg"
          onClick={() => complete.mutate()}
          disabled={complete.isPending || !hasSelectedDomain || !hasConfirmedIcp(profile)}
          className="text-sm font-medium"
        >
          {complete.isPending ? 'Creating…' : 'Create project'}
        </Button>
        <Button variant="ghost" size="lg" onClick={() => setStep(1)} disabled={complete.isPending}>
          Back
        </Button>
      </div>
    </div>
  );
}

function warningMessage(code: string): string {
  const messages: Record<string, string> = {
    research_degraded:
      'Some research was unavailable. We prepared a market-aware fallback for you to edit.',
    competitors_not_found:
      'No competitors were confirmed. You can continue with none or add them yourself.',
    site_health_deferred:
      'The project is ready; its Site Health review will need to be started later.',
  };
  return (
    messages[code] ??
    'Some research could not be confirmed. Review the suggestions before continuing.'
  );
}

function toggleCompetitor(
  index: number,
  setCompetitors: React.Dispatch<
    React.SetStateAction<import('@/lib/onboarding/forms').ReviewCompetitor[]>
  >,
  maximum: number | undefined,
) {
  setCompetitors((items) => {
    const selected = items.filter((item) => item.selected).length;
    return items.map((item, itemIndex) =>
      itemIndex !== index || (!item.selected && (maximum === undefined || selected >= maximum))
        ? item
        : { ...item, selected: !item.selected },
    );
  });
}

function editCompetitorDomain(
  index: number,
  domain: string,
  setCompetitors: React.Dispatch<
    React.SetStateAction<import('@/lib/onboarding/forms').ReviewCompetitor[]>
  >,
) {
  setCompetitors((items) =>
    items.map((item, itemIndex) =>
      itemIndex === index ? { ...item, domains: [domain], name: item.name || domain } : item,
    ),
  );
}

function addCompetitor(
  setCompetitors: React.Dispatch<
    React.SetStateAction<import('@/lib/onboarding/forms').ReviewCompetitor[]>
  >,
  maximum: number | undefined,
) {
  setCompetitors((items) => {
    if (maximum === undefined || items.filter((item) => item.selected).length >= maximum)
      return items;
    const id = globalThis.crypto.randomUUID();
    return [
      ...items,
      { id: `competitor:manual:${id}`, name: '', aliases: [], domains: [], selected: true },
    ];
  });
}
