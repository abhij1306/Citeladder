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
    <form noValidate onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-1">
        <h1 className="text-foreground text-2xl font-semibold tracking-[-0.025em]">
          {isAdditional ? 'Add a project' : "Let's get started"}
        </h1>
        <p className="text-muted text-sm">
          We&apos;ll review your website, suggest comparable brands, and prepare balanced questions.
        </p>
      </div>
      <div className="grid items-start gap-x-5 gap-y-4 sm:grid-cols-2">
        <Field label="Brand name" required error={form.formState.errors.brand_name?.message}>
          {(props) => (
            <Input {...props} {...form.register('brand_name')} placeholder="Acme" size="md" />
          )}
        </Field>
        <Field label="Website" required error={form.formState.errors.website_url?.message}>
          {(props) => (
            <Input
              {...props}
              {...form.register('website_url')}
              placeholder="acme.com"
              inputMode="url"
              size="md"
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
      <div className="flex items-center gap-3 pt-1">
        <Button type="submit" size="md" className="text-sm font-medium">
          Continue
        </Button>
        {isAdditional ? (
          <Button asChild variant="ghost" size="md">
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
        <h1 className="text-foreground text-2xl font-semibold tracking-[-0.025em]">
          Finding what to track
        </h1>
        <p className="text-muted text-sm">
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
        <Alert key={warning} tone="warning">
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
        <Alert tone="warning">
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
      <div className="flex items-center gap-3 pt-1">
        <Button
          size="md"
          onClick={onReview}
          disabled={
            discovery.isRunning || !discovery.discovery || discovery.discovery.status !== 'ready'
          }
          className="text-sm font-medium"
        >
          {discovery.isRunning ? 'Searching…' : 'Review'}
        </Button>
        <Button variant="ghost" size="md" onClick={onEdit}>
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
    completionFailed,
    domains,
    hasSelectedDomain,
    isCompleting,
    maximumCompetitors,
    profile,
    setCompetitors,
    setProfile,
    setStep,
    toggle,
  } = flow;
  return (
    <div className="space-y-3.5">
      <div className="space-y-1">
        <h1 className="text-foreground text-2xl font-semibold tracking-[-0.025em]">
          Does this look right?
        </h1>
        <p className="text-muted text-sm">
          Deselect anything you don&apos;t want — you can change all of it after setup.
        </p>
      </div>
      <div className="grid gap-3">
        <section className="border-border bg-panel shadow-card flex flex-col gap-2 rounded-[var(--radius-card)] border p-4">
          <div className="border-border-subtle flex items-center justify-between border-b pb-2">
            <span className="text-muted text-2xs font-semibold tracking-[0.06em] uppercase">
              Brand Positioning &amp; Market
            </span>
            <span className="bg-accent-soft text-accent-text border-accent-border/50 text-2xs inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-semibold">
              <span className="bg-accent size-1.5 rounded-full" aria-hidden />
              AI Discovered
            </span>
          </div>
          {profile ? <IcpConfirmation profile={profile} onChange={setProfile} /> : null}
        </section>
        <section className="border-border bg-panel shadow-card flex flex-col gap-2 rounded-[var(--radius-card)] border p-4">
          <div className="border-border-subtle flex items-center justify-between border-b pb-2">
            <span className="text-muted text-2xs font-semibold tracking-[0.06em] uppercase">
              Online Footprint &amp; Peers
            </span>
            <span className="text-2xs text-muted font-medium">Auto-verified domains</span>
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
        </section>
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
        <Alert tone="warning">{onboardingErrorMessage(complete.error)}</Alert>
      ) : null}
      <CompletionStateAlert failed={completionFailed} />
      {!hasSelectedDomain ? (
        <Alert tone="warning">Keep at least one website address selected.</Alert>
      ) : null}
      {!hasConfirmedIcp(profile) ? (
        <Alert tone="warning">Choose or describe what you sell.</Alert>
      ) : null}
      <div className="border-border-subtle flex items-center justify-between gap-3 border-t pt-3">
        <Button variant="secondary" size="md" onClick={() => setStep(1)} disabled={isCompleting}>
          Back
        </Button>
        <Button
          size="md"
          onClick={() => complete.mutate()}
          disabled={
            completionFailed || isCompleting || !hasSelectedDomain || !hasConfirmedIcp(profile)
          }
        >
          {isCompleting ? 'Creating…' : 'Create project'}
        </Button>
      </div>
    </div>
  );
}

function CompletionStateAlert({ failed }: Readonly<{ failed: boolean }>) {
  if (failed) {
    return (
      <Alert tone="danger">
        Project creation did not finish. Go back, confirm the website again, and retry.
      </Alert>
    );
  }
  return null;
}

function warningMessage(code: string): string {
  const messages: Record<string, string> = {
    research_degraded:
      'We used the website details we could confirm. Review them before continuing.',
    competitors_not_found:
      'No competitors were confirmed. You can continue with none or add them yourself.',
    external_research_unavailable:
      'We used the website details we could confirm. Review them before continuing.',
    external_research_no_results:
      'We used the website details we could confirm. Review them before continuing.',
    conflicting_evidence:
      'Sources disagreed about this business. Review the suggested positioning carefully.',
    topic_selection_unavailable:
      'Your starting topics will be created from the offerings you confirm.',
    insufficient_offering_evidence:
      'Your starting topics will be created from the offerings you confirm.',
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
