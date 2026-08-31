import type { CSSProperties } from 'react';
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
    <form id="onboarding-brand-form" noValidate onSubmit={onSubmit}>
      <div className="flow-header">
        <h1 className="flow-title">{isAdditional ? 'Add a project' : "Let's get started"}</h1>
        <p className="website-body">
          We&apos;ll review your website, suggest comparable brands, and prepare balanced questions.
        </p>
      </div>
      <div className="grid items-start gap-x-5 gap-y-4 sm:grid-cols-2">
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
    </form>
  );
}

export function DiscoveryStage({
  brandName,
  discovery,
  onEdit,
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
}>) {
  const found = discoveryResults(discovery.discovery);
  return (
    <div>
      <div className="flow-header">
        <h1 className="flow-title">Finding what to track</h1>
        <p className="website-body">
          We&apos;re reading {brandName || 'your website'} and learning what you offer.
        </p>
      </div>
      <ActivityProgress
        label="Discovering your brand"
        steps={discoveryActivity(discovery.discovery)}
        animateCompletion
        appearance="flow"
      />
      {found.length > 0 ? (
        <section className="flow-found">
          <h2 className="flow-group-title">Found so far</h2>
          <ul className="flow-found-list">
            {found.map((item, index) => (
              <li
                key={`${item}:${index}`}
                className="flow-found-item"
                style={{ '--flow-result-index': index } as CSSProperties}
              >
                {item}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <div className="mt-[var(--flow-block)] grid gap-[var(--flow-answer)]">
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
    maximumCompetitors,
    profile,
    setCompetitors,
    setProfile,
    toggle,
  } = flow;
  return (
    <div>
      <div className="flow-header">
        <h1 className="flow-title">Does this look right?</h1>
        <p className="website-body">
          Everything below was found automatically. Deselect anything you don&apos;t want to track.
        </p>
      </div>
      <div className="flow-groups">
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
        {profile ? <IcpConfirmation profile={profile} onChange={setProfile} /> : null}
      </div>
      <div className="mt-[var(--flow-block)] grid gap-[var(--flow-answer)]">
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
      </div>
    </div>
  );
}

function discoveryResults(
  discovery: ReturnType<
    typeof import('@/lib/onboarding/use-brand-discovery').useBrandDiscovery
  >['discovery'],
): string[] {
  if (!discovery) return [];
  const website = String(discovery.input_data.website_url ?? '').replace(/^https?:\/\//, '');
  return [website, ...discovery.competitors.map((competitor) => competitor.name)].filter(Boolean);
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
