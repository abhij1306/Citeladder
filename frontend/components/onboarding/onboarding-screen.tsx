'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { Check } from 'lucide-react';

import { AuthWordmark, BrandCanvas } from '@/components/auth/brand-panel';
import { Alert } from '@/components/ui/alert';
import { ActivityProgress } from '@/components/ui/activity-progress';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { MarketSelect } from '@/components/ui/market-select';
import { queryKeys } from '@/lib/api/query-keys';
import { projectsApi } from '@/lib/api/projects';
import { brandDiscoveriesApi, type DiscoveryProfile } from '@/lib/api/brand-discoveries';
import {
  brandStepSchema,
  emptyBrandStep,
  normalizeWebsiteUrl,
  onboardingErrorMessage,
  type BrandStepValues,
  type ReviewCompetitor,
  type ReviewDomain,
} from '@/lib/onboarding/forms';
import { useBrandDiscovery } from '@/lib/onboarding/use-brand-discovery';
import { discoveryActivity } from '@/lib/onboarding/discovery-activity';
import { useProjectContext } from '@/lib/project/project-context';
import { cn } from '@/lib/utils';
import { COUNTRY_OPTIONS, LANGUAGE_OPTIONS } from '@/lib/setup/markets';

import { ReviewStep } from './review-step';
import { hasConfirmedIcp, IcpConfirmation } from './icp-confirmation';

/**
 * Fill brand-knowledge fields the confirm screen no longer asks for.
 *
 * They remain required by the completion contract and editable later on the
 * brand screen; onboarding just stops making the user author them. Falling back
 * to the confirmed category keeps the payload truthful rather than inventing
 * marketing copy.
 */
function withBrandKnowledgeDefaults(profile: DiscoveryProfile): DiscoveryProfile {
  const category = profile.category.trim();
  const products = profile.products_services.filter((item) => item.trim());
  return {
    ...profile,
    positioning: profile.positioning.trim() || category,
    target_audience: profile.target_audience.trim() || 'Buyers searching for ' + category,
    products_services: products.length > 0 ? products : [category],
  };
}

/**
 * Onboarding — the only way a project gets created (plan.md §10, decision 11;
 * `/setup` is retired).
 *
 * Three steps: Brand → Discovery → Review, framed by a slim header
 * (logo + compact inline stepper) and a centered card per step. Brand and
 * Discovery hold a narrow measure; Review widens to the pane and splits into
 * confirm-on-the-left / discovered-on-the-right, because it is a dense grid of
 * chips rather than a short form. Discovery fires all three suggestion calls
 * automatically on entry; there is no Generate button, because discovery is
 * the reason the screen exists.
 *
 * Second project onward (`?new=1`) runs the identical flow — the discovery is
 * the value, not a first-run formality — with two differences: the copy drops
 * the welcome framing, and Cancel returns to `/projects` instead of leaving the
 * user nowhere.
 */
/**
 * The three stages, as DATA. The stepper needs a title and a description per
 * step; deriving them from a bare label with nested ternaries at the render
 * site meant three separate chains had to be kept in the same order as the
 * array, and adding a step meant editing each one.
 */
const STEPS = [
  { id: 'brand', title: 'Basic information', description: 'Name & domain details' },
  { id: 'discovery', title: 'AI Research', description: 'Auto-finding competitors' },
  { id: 'review', title: 'Confirm ICP', description: 'Finalize facts & tracking scope' },
] as const;
const MARKET_OPTIONS = [{ value: 'GLOBAL', label: 'Global' }, ...COUNTRY_OPTIONS];
type StepIndex = 0 | 1 | 2;

function selectedDomainValues(domains: ReviewDomain[]): string[] {
  return domains.flatMap((item) => (item.selected ? [item.domain] : []));
}

function selectedCompetitorValues(competitors: ReviewCompetitor[]) {
  return competitors.flatMap((item) =>
    item.selected && item.name.trim()
      ? [{ name: item.name.trim(), aliases: item.aliases, domains: item.domains }]
      : [],
  );
}

function stepQueryValue(step: StepIndex): 'brand' | 'discovery' | 'review' {
  if (step === 2) return 'review';
  if (step === 1) return 'discovery';
  return 'brand';
}

function manualCompetitorId(): string {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `fallback-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

function warningMessage(code: string): string {
  if (code === 'research_degraded') {
    return 'Some research was unavailable. We prepared a market-aware fallback for you to edit.';
  }
  if (code === 'competitors_not_found') {
    return 'No competitors were confirmed. You can continue with none or add them yourself.';
  }
  if (code === 'site_health_deferred') {
    return 'The project is ready; its Site Health review will need to be started later.';
  }
  return 'Some research could not be confirmed. Review the suggestions before continuing.';
}

// react-doctor-disable-next-line react-doctor/no-giant-component -- this is the wizard transaction owner; discovery, review, and field controls are already extracted components.
export function OnboardingScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { setActiveProjectId } = useProjectContext();
  const isAdditional = searchParams?.get('new') === '1';
  const initialDiscoveryId = searchParams?.get('discovery') ?? null;

  const [step, setStep] = useState<StepIndex>(() => {
    if (!initialDiscoveryId) return 0;
    return searchParams?.get('step') === 'review' ? 2 : 1;
  });
  const [resumeDiscoveryId, setResumeDiscoveryId] = useState<string | null>(initialDiscoveryId);
  const [brand, setBrand] = useState<BrandStepValues | null>(null);
  const [domains, setDomains] = useState<ReviewDomain[]>([]);
  const [competitors, setCompetitors] = useState<ReviewCompetitor[]>([]);
  const [profile, setProfile] = useState<DiscoveryProfile | null>(null);
  const hasSelectedDomain = domains.some((item) => item.selected);
  const form = useForm<BrandStepValues>({
    resolver: zodResolver(brandStepSchema),
    defaultValues: emptyBrandStep,
  });

  const discovery = useBrandDiscovery(
    step >= 1 && brand
      ? {
          brand_name: brand.brand_name.trim(),
          website_url: normalizeWebsiteUrl(brand.website_url),
          industry: brand.industry,
          subindustry: brand.subindustry,
          primary_market: brand.primary_market,
          language_code: brand.language_code,
        }
      : null,
    resumeDiscoveryId,
  );
  const discoveryCatalog = useQuery({
    queryKey: ['brand-discovery-catalog'],
    queryFn: ({ signal }) => brandDiscoveriesApi.catalog({ signal }),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const maximumCompetitors = discoveryCatalog.data?.maximum_competitors;
  // Seed the editable review lists once each section lands. Guarded on length
  // so re-renders never clobber the user's selections mid-review.
  const discoveryState = discovery.discovery;
  useEffect(() => {
    if (brand || !discoveryState) return;
    const value = discoveryState.input_data;
    const text = (key: string, fallback = '') =>
      typeof value[key] === 'string' ? (value[key] as string) : fallback;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate the persisted draft once.
    setBrand({
      brand_name: text('brand_name'),
      website_url: text('website_url'),
      industry: text('industry'),
      subindustry: text('subindustry'),
      primary_market: text('primary_market', 'US'),
      language_code: text('language_code', 'en'),
    });
  }, [brand, discoveryState]);

  useEffect(() => {
    const discoveryId = discoveryState?.id ?? resumeDiscoveryId;
    if (!discoveryId) return;
    if (resumeDiscoveryId !== discoveryId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- mirror the persisted discovery id.
      setResumeDiscoveryId(discoveryId);
    }
    const params = new URLSearchParams(searchParams?.toString() ?? '');
    params.set('discovery', discoveryId);
    params.set('step', stepQueryValue(step));
    const next = params.toString();
    if (next !== searchParams?.toString()) router.replace(`/onboarding?${next}`, { scroll: false });
  }, [discoveryState?.id, resumeDiscoveryId, router, searchParams, step]);
  useEffect(() => {
    if (discoveryState?.status === 'ready') {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- seed an editable persisted draft.
      setDomains((prev) =>
        prev.length > 0
          ? prev
          : discoveryState.domains.map((domain, index) => ({
              id: `domain:${index}:${domain}`,
              domain,
              selected: true,
            })),
      );
      setProfile((previous) => previous ?? discoveryState.profile);
    }
  }, [discoveryState]);

  useEffect(() => {
    if (maximumCompetitors !== undefined && discoveryState?.status === 'ready') {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- seed an editable persisted draft.
      setCompetitors((prev) =>
        prev.length > 0
          ? prev
          : discoveryState.competitors.map((competitor, index) => ({
              ...competitor,
              id: `competitor:${index}:${competitor.name}`,
              selected: index < maximumCompetitors,
            })),
      );
    }
  }, [discoveryState, maximumCompetitors]);

  // One idempotent request owns every write, including the first site review.
  // A retry therefore cannot leave behind or duplicate a partial project.
  const complete = useMutation({
    mutationFn: async () => {
      if (!brand || !discovery.discovery || !hasConfirmedIcp(profile)) {
        throw new Error('Confirm the required ICP fields before creating the project.');
      }

      return brandDiscoveriesApi.complete(
        discovery.discovery.id,
        {
          name: brand.brand_name.trim(),
          profile: withBrandKnowledgeDefaults(profile),
          domains: selectedDomainValues(domains),
          competitors: selectedCompetitorValues(competitors),
        },
        `complete:${discovery.discovery.id}`,
      );
    },
    onSuccess: async (result) => {
      setActiveProjectId(result.project_id);
      // Logo hydration is best-effort and never blocks onboarding. The backend
      // checks its database cache before crawling; once it finishes, refresh
      // the project list so every shared BrandLogo instance updates together.
      void projectsApi
        .refreshProjectLogos(result.project_id)
        .then(() => queryClient.invalidateQueries({ queryKey: queryKeys.projects.list() }))
        .catch(() => undefined);
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects.list() });
      const params = new URLSearchParams({ project: result.project_id });
      if (result.crawl_id) {
        params.set('activation', '1');
        params.set('crawl', result.crawl_id);
        if (result.page_limit !== null) params.set('limit', String(result.page_limit));
      }
      router.replace(`/projects?${params.toString()}`);
    },
  });

  const submitBrand = form.handleSubmit((values) => {
    // Correcting the brand starts a NEW discovery run, so the review lists must
    // be emptied first: the seeding effects bail out when `prev.length > 0` and
    // would otherwise leave the previous brand's results standing in front of
    // the new ones. Back → Continue with unchanged values re-runs nothing,
    // so clearing there would blank the review step for good.
    const rediscovers = brand !== null && JSON.stringify(brand) !== JSON.stringify(values);
    if (rediscovers) {
      setDomains([]);
      setCompetitors([]);
      setProfile(null);
      setResumeDiscoveryId(null);
    }
    setBrand(values);
    setStep(1);
  });

  const toggle = useCallback(
    <T extends { selected: boolean }>(setter: React.Dispatch<React.SetStateAction<T[]>>) =>
      (index: number) =>
        setter((prev) =>
          prev.map((item, i) => (i === index ? { ...item, selected: !item.selected } : item)),
        ),
    [],
  );

  return (
    <div className="website-type bg-panel text-foreground selection:bg-accent selection:text-accent-fg relative h-screen max-h-screen w-full overflow-hidden antialiased min-[900px]:grid min-[900px]:grid-cols-12">
      {/* Left Brand Panel — Vertical Stepper (Desktop ≥900px) */}
      <BrandCanvas className="col-span-5 h-screen max-h-screen justify-between p-6 lg:col-span-4 xl:p-10">
        <div className="relative z-10 flex flex-col gap-8">
          <AuthWordmark light />

          <div className="space-y-1.5">
            <h2 className="website-feature-heading text-brand-canvas-foreground">
              Set up your project
            </h2>
            <p className="website-body text-brand-canvas-secondary">
              Create your workspace in a few clicks.
            </p>
          </div>

          {/* Vertical Stepper Flow. The connector is a SIBLING of the list:
              `ol` permits only `li` (plus script/template) as content, and a
              bare decorative `div` inside it is invalid markup. */}
          <div className="relative my-auto">
            <div
              className="bg-brand-canvas-border absolute top-4 bottom-4 left-4.5 w-0.5"
              aria-hidden="true"
            />
            <ol className="relative list-none space-y-10 p-0 pl-1 sm:space-y-12">
              {STEPS.map((stage, index) => {
                const isDone = index < step;
                const isCurrent = index === step;
                return (
                  <li
                    key={stage.id}
                    aria-current={isCurrent ? 'step' : undefined}
                    className="relative flex items-center gap-4"
                  >
                    <span
                      className={cn(
                        'relative z-10 flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-bold transition-all sm:size-10',
                        isDone && 'bg-accent text-accent-fg shadow-accent/30 shadow-md',
                        isCurrent && 'bg-accent text-accent-fg ring-accent/20 ring-4',
                        !isDone &&
                          !isCurrent &&
                          'border-brand-canvas-border bg-brand-canvas-raised text-brand-canvas-muted border',
                      )}
                    >
                      {isDone ? (
                        <>
                          <Check className="size-4.5" strokeWidth={2.5} aria-hidden="true" />
                          <span className="sr-only">Completed:</span>
                        </>
                      ) : (
                        index + 1
                      )}
                    </span>
                    <div className="space-y-1">
                      <p
                        className={cn(
                          'website-small-heading transition-colors',
                          isCurrent && 'text-brand-canvas-foreground',
                          isDone && 'text-brand-canvas-secondary',
                          !isDone && !isCurrent && 'text-brand-canvas-muted',
                        )}
                      >
                        {stage.title}
                      </p>
                      <p className="website-label text-brand-canvas-muted">{stage.description}</p>
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
        </div>

        <div className="website-label border-brand-canvas-border/80 text-brand-canvas-muted relative z-10 border-t pt-4">
          <span>© {new Date().getFullYear()} CiteLadder · Onboarding</span>
        </div>
      </BrandCanvas>

      {/* Right Canvas — Form & Details */}
      <div className="bg-panel relative col-span-12 flex h-screen max-h-screen flex-col justify-between overflow-hidden p-6 min-[900px]:col-span-7 sm:px-8 sm:py-6 lg:col-span-8 lg:px-10 lg:py-8 xl:py-10">
        {/* Mobile Header (<900px) */}
        <header className="border-border-subtle border-b pb-3 min-[900px]:hidden">
          <div className="flex items-center justify-between gap-4">
            <AuthWordmark compact />
            <ol className="flex list-none items-center gap-2 p-0">
              {STEPS.map((stage, index) => {
                const state = index < step ? 'done' : index === step ? 'current' : 'upcoming';
                return (
                  <li key={stage.id} className="flex items-center">
                    <span
                      aria-current={state === 'current' ? 'step' : undefined}
                      className={cn(
                        'flex size-6 items-center justify-center rounded-full text-xs font-semibold',
                        state === 'current'
                          ? 'bg-accent text-accent-fg'
                          : state === 'done'
                            ? 'bg-success text-accent-fg'
                            : 'border-border-subtle bg-well text-muted border',
                      )}
                    >
                      {state === 'done' ? (
                        <Check className="size-3" strokeWidth={3} aria-hidden="true" />
                      ) : (
                        index + 1
                      )}
                      {/* The dot alone is not a label: a screen reader would
                          otherwise announce a bare number, or nothing at all
                          once the check replaces it. */}
                      <span className="sr-only">{stage.title}</span>
                    </span>
                  </li>
                );
              })}
            </ol>
          </div>
        </header>

        {/* Step Stage Content — Top aligned across all steps so headers start at the same vertical offset */}
        {/* The stage OWNS the vertical scroll. Its ancestors are
            `h-screen overflow-hidden`, so without this a review step taller
            than the viewport — or any step on a short laptop — clipped its
            own action row with nothing able to scroll to it. `min-h-0` is
            what lets a flex child shrink below its content and actually
            scroll instead of stretching the column, and `overflow-y-auto` is
            what makes the overflow reachable at all — without it the rail is
            declared and nothing scrolls. `auto` keeps ordinary laptop
            viewports free of a stray scrollbar while short screens and
            unusually long discovered content stay reachable. */}
        {/* The rail WIDTH follows the step's content, it is not one constant.
            A two-field form wants a narrow measure; the review step is a dense
            grid of chips that was being squeezed into the same 576px and
            stacked into a tall vertical ribbon with most of the pane empty
            beside it. Same rail for both meant one of them was always wrong. */}
        <main
          id="main"
          className={cn(
            'mx-auto flex min-h-0 w-full flex-1 flex-col justify-center overflow-y-auto py-2 text-sm sm:py-3 lg:py-4',
            step === 2 ? 'max-w-6xl' : 'max-w-xl',
          )}
        >
          <div className="p-1 sm:p-2">
            {step === 0 ? (
              <form noValidate onSubmit={submitBrand} className="space-y-6">
                <div className="space-y-1">
                  <h1 className="website-feature-heading text-foreground">
                    {isAdditional ? 'Add a project' : "Let's get started"}
                  </h1>
                  <p className="website-body text-muted">
                    We&apos;ll review your website, suggest comparable brands, and prepare balanced
                    questions.
                  </p>
                </div>

                <div className="grid items-start gap-x-6 gap-y-5 sm:grid-cols-2">
                  <Field
                    label="Brand name"
                    required
                    error={form.formState.errors.brand_name?.message}
                  >
                    {(props) => (
                      <Input
                        {...props}
                        {...form.register('brand_name')}
                        placeholder="Acme"
                        size="lg"
                      />
                    )}
                  </Field>
                  <Field
                    label="Website"
                    required
                    error={form.formState.errors.website_url?.message}
                  >
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
                  {/* Industry and sub-industry are no longer asked for: they
                      are resolved from the site and the model, then shown for
                      confirmation on the review step. Asking produced worse
                      results than inferring, because a fixed list has no entry
                      for most real businesses. */}
                  <Field
                    label="Primary market"
                    error={form.formState.errors.primary_market?.message}
                  >
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
            ) : null}

            {step === 1 ? (
              <div className="space-y-4">
                <div className="space-y-1">
                  <h1 className="website-feature-heading text-foreground">Finding what to track</h1>
                  <p className="website-body text-muted">
                    We&apos;re learning about {brand?.brand_name || 'your brand'} and preparing
                    useful questions. You can review everything before the project is created.
                  </p>
                </div>

                <div className="border-border-subtle bg-well/40 rounded-xl border p-3.5">
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
                      <Button size="sm" variant="ghost" onClick={() => setStep(0)}>
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
                    onClick={() => setStep(2)}
                    disabled={
                      discovery.isRunning ||
                      !discovery.discovery ||
                      discovery.discovery.status !== 'ready'
                    }
                    className="text-sm font-medium"
                  >
                    {discovery.isRunning ? 'Searching…' : 'Review'}
                  </Button>
                  <Button variant="ghost" size="lg" onClick={() => setStep(0)}>
                    Back
                  </Button>
                </div>
              </div>
            ) : null}

            {step === 2 ? (
              <div className="space-y-3">
                {/* The title sits on the action row rather than above it. This
                    step is a review, not a page: a 24px display heading over a
                    full-width paragraph spent the top of the screen announcing
                    a question the content answers by itself. */}
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <h1 className="website-body text-foreground font-semibold">
                    Does this look right?
                  </h1>
                  <p className="website-label text-muted">
                    Deselect anything you don&apos;t want — you can change all of it after setup.
                  </p>
                </div>

                {/* ONE panel, split into two columns on a wide screen: what the
                    user CONFIRMS on the left, what we DISCOVERED on the right.
                    They stacked before, so a review that fits side by side ran
                    down a 576px ribbon with two-thirds of the pane empty next
                    to it. Rendering the questions bare and the lists as their
                    own bordered cards also said the two halves were unrelated,
                    and gave the least important part the heaviest container. */}
                <div className="border-border-subtle bg-panel divide-border-subtle grid divide-y rounded-xl border lg:grid-cols-2 lg:divide-x lg:divide-y-0">
                  <div className="divide-border-subtle divide-y px-4 py-3">
                    {profile ? <IcpConfirmation profile={profile} onChange={setProfile} /> : null}
                  </div>

                  <ReviewStep
                    domains={domains}
                    competitors={competitors}
                    onToggleDomain={toggle(setDomains)}
                    onToggleCompetitor={(index) =>
                      setCompetitors((previous) => {
                        const selectedCount = previous.filter((item) => item.selected).length;
                        return previous.map((item, itemIndex) => {
                          if (itemIndex !== index) return item;
                          if (
                            !item.selected &&
                            (maximumCompetitors === undefined ||
                              selectedCount >= maximumCompetitors)
                          ) {
                            return item;
                          }
                          return { ...item, selected: !item.selected };
                        });
                      })
                    }
                    onEditCompetitorDomain={(index, domain) =>
                      setCompetitors((prev) =>
                        prev.map((item, i) =>
                          i === index
                            ? {
                                ...item,
                                domains: [domain],
                                // A manually added competitor has no name yet, and
                                // the submit payload drops any competitor whose
                                // name is blank — so the domain doubles as the
                                // name until the user gives it one. A discovered
                                // competitor keeps the name it came with.
                                name: item.name || domain,
                              }
                            : item,
                        ),
                      )
                    }
                    onAddCompetitor={() =>
                      setCompetitors((prev) => {
                        const selectedCount = prev.filter((item) => item.selected).length;
                        if (
                          maximumCompetitors === undefined ||
                          selectedCount >= maximumCompetitors
                        ) {
                          return prev;
                        }
                        return [
                          ...prev,
                          {
                            id: `competitor:manual:${manualCompetitorId()}`,
                            name: '',
                            aliases: [],
                            domains: [],
                            selected: true,
                          },
                        ];
                      })
                    }
                    maximumCompetitors={maximumCompetitors}
                  />
                </div>

                {discoveryCatalog.isError ? (
                  <Alert tone="warning">
                    <div className="flex items-center justify-between gap-3">
                      <span>We could not load the competitor limit.</span>
                      <Button size="sm" variant="ghost" onClick={() => discoveryCatalog.refetch()}>
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
                  <Button
                    variant="ghost"
                    size="lg"
                    onClick={() => setStep(1)}
                    disabled={complete.isPending}
                  >
                    Back
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
        </main>
      </div>
    </div>
  );
}
