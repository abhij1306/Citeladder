'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { Check } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { ActivityProgress } from '@/components/ui/activity-progress';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { LogoMark } from '@/components/ui/logo-mark';
import { MarketSelect } from '@/components/ui/market-select';
import { queryKeys } from '@/lib/api/query-keys';
import { projectsApi } from '@/lib/api/projects';
import { brandDiscoveriesApi } from '@/lib/api/brand-discoveries';
import {
  brandStepSchema,
  emptyBrandStep,
  normalizeWebsiteUrl,
  onboardingErrorMessage,
  type BrandStepValues,
  type ReviewCompetitor,
  type ReviewDomain,
  type ReviewPrompt,
} from '@/lib/onboarding/forms';
import { useBrandDiscovery } from '@/lib/onboarding/use-brand-discovery';
import { discoveryActivity } from '@/lib/onboarding/discovery-activity';
import { useProjectContext } from '@/lib/project/project-context';
import { cn } from '@/lib/utils';
import { COUNTRY_OPTIONS, LANGUAGE_OPTIONS } from '@/lib/setup/markets';

import { ReviewStep } from './review-step';

/**
 * Onboarding — the only way a project gets created (plan.md §10, decision 11;
 * `/setup` is retired).
 *
 * Three steps: Brand → Discovery → Review, framed by a slim header
 * (logo + compact inline stepper) and a centered card per step. The review
 * step widens to a two-column grid so the whole review fits without a nested-
 * card scroll. Discovery fires all three suggestion calls automatically on
 * entry; there is no Generate button, because discovery is the reason the
 * screen exists.
 *
 * Second project onward (`?new=1`) runs the identical flow — the discovery is
 * the value, not a first-run formality — with two differences: the copy drops
 * the welcome framing, and Cancel returns to `/projects` instead of leaving the
 * user nowhere.
 */
const STEPS = ['Brand', 'Discovery', 'Review'] as const;
type StepIndex = 0 | 1 | 2;

/**
 * Per-step stage geometry. The short form/progress/congrats steps are narrow
 * cards centered both ways; the data-dense review step is wide, top-aligned,
 * and flex-height so its internal columns fill the stage rather than scroll it.
 */
const STEP_STAGE: Record<StepIndex, { maxWidth: string; centerY: string; stageAlign: string }> = {
  0: { maxWidth: 'max-w-3xl', centerY: 'justify-center', stageAlign: 'sm:justify-center' },
  1: { maxWidth: 'max-w-3xl', centerY: 'justify-center', stageAlign: 'sm:justify-center' },
  2: { maxWidth: 'max-w-4xl', centerY: 'justify-center', stageAlign: 'sm:justify-center' },
};

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
  const [prompts, setPrompts] = useState<ReviewPrompt[]>([]);
  const hasSelectedDomain = domains.some((item) => item.selected);
  const hasSelectedPrompt = prompts.some((item) => item.selected);
  const selectedPromptCount = prompts.filter((item) => item.selected).length;
  const selectedComparisonCount = prompts.filter(
    (item) => item.selected && item.cohort === 'comparison',
  ).length;
  const hasBalancedPromptPortfolio =
    selectedComparisonCount <= Math.floor(selectedPromptCount * 0.2);
  const selectedCompetitorNames = competitors
    .filter((item) => item.selected && item.name.trim())
    .flatMap((item) => [item.name, ...item.aliases])
    .map((name) => name.trim().toLocaleLowerCase())
    .filter(Boolean);
  const comparisonsMatchSelectedCompetitors = prompts
    .filter((item) => item.selected && item.cohort === 'comparison')
    .every((prompt) => {
      const text = prompt.text.toLocaleLowerCase();
      return selectedCompetitorNames.some((name) => text.includes(name));
    });
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
          country_code: brand.country_code,
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
    // eslint-disable-next-line react-hooks/set-state-in-effect -- restore the persisted discovery after reload/back navigation.
    setBrand({
      brand_name: text('brand_name'),
      website_url: text('website_url'),
      industry: text('industry'),
      country_code: text('country_code', 'US'),
      language_code: text('language_code', 'en'),
    });
  }, [brand, discoveryState]);

  useEffect(() => {
    const discoveryId = discoveryState?.id ?? resumeDiscoveryId;
    if (!discoveryId) return;
    if (resumeDiscoveryId !== discoveryId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- retain the server identity so later navigation never creates a duplicate discovery.
      setResumeDiscoveryId(discoveryId);
    }
    const params = new URLSearchParams(searchParams?.toString() ?? '');
    params.set('discovery', discoveryId);
    params.set('step', stepQueryValue(step));
    const next = params.toString();
    if (next !== searchParams?.toString()) router.replace(`/onboarding?${next}`, { scroll: false });
  }, [discoveryState?.id, resumeDiscoveryId, router, searchParams, step]);
  useEffect(() => {
    if (discoveryState && ['ready', 'needs_input'].includes(discoveryState.status)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- seed editable state from a completed discovery result.
      setDomains((prev) =>
        prev.length > 0
          ? prev
          : discoveryState.domains.map((domain, index) => ({
              id: `domain:${index}:${domain}`,
              domain,
              selected: true,
            })),
      );
      setPrompts((previous) =>
        previous.length > 0
          ? previous
          : discoveryState.prompt_suggestions.map((prompt, index) => ({
              ...prompt,
              id: `prompt:${index}:${prompt.text}`,
              selected: true,
            })),
      );
    }
  }, [discoveryState]);

  useEffect(() => {
    if (
      maximumCompetitors !== undefined &&
      discoveryState &&
      ['ready', 'needs_input'].includes(discoveryState.status)
    ) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- seed editable state from a completed discovery result.
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
      if (!brand || !discovery.discovery) throw new Error('Discovery details are missing.');
      const selectedPrompts = prompts.filter((item) => item.selected);
      const groupedPrompts = new Map<string, typeof selectedPrompts>();
      for (const prompt of selectedPrompts) {
        const topic = (prompt.theme ?? '').trim() || brand.industry.trim() || 'General';
        groupedPrompts.set(topic, [...(groupedPrompts.get(topic) ?? []), prompt]);
      }

      return brandDiscoveriesApi.complete(
        discovery.discovery.id,
        {
          name: brand.brand_name.trim(),
          profile: discovery.discovery.profile,
          domains: domains.filter((item) => item.selected).map((item) => item.domain),
          competitors: competitors
            .filter((item) => item.selected && item.name.trim())
            .map((item) => ({
              name: item.name.trim(),
              aliases: item.aliases,
              domains: item.domains,
            })),
          prompt_groups: [...groupedPrompts.entries()].map(([topic, topicPrompts]) => ({
            topic,
            prompts: topicPrompts.map(({ text, intent, cohort }) => ({ text, intent, cohort })),
          })),
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
      router.replace(
        `/projects?activation=1&project=${encodeURIComponent(result.project_id)}&crawl=${encodeURIComponent(result.crawl_id)}&limit=${result.page_limit}`,
      );
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
      setPrompts([]);
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
    // The viewport-height flex chain (min-h-dvh col → flex-1 overflow-y stage →
    // h-full step) keeps short steps floating on the ambient background with
    // centered tight cards instead of a tall white slab; the review step fills
    // the stage with a two-column grid instead of one long scroll.
    <div className="bg-background text-foreground selection:bg-accent selection:text-accent-fg relative flex min-h-dvh flex-col antialiased">
      {/* Background ambient lighting */}
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="bg-accent-subtle/40 absolute -top-40 -left-40 size-125 rounded-full blur-[120px]" />
        <div className="bg-accent-subtle/40 absolute -right-40 -bottom-40 size-125 rounded-full blur-[120px]" />
      </div>

      {/* Opaque surface, no blur: the elevation guard (design.md §4a) keeps
          gradients and blur to display art, never a control container. */}
      <header className="border-border-subtle/80 bg-panel border-b py-3">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 sm:gap-6 sm:px-6 lg:px-8">
          <span className="flex shrink-0 items-center gap-2">
            <LogoMark size={24} />
            <span className="font-display text-foreground text-base font-bold">CiteLadder</span>
          </span>

          {/* Compact inline stepper — replaces the old dedicated stepper card. */}
          <ol className="mx-auto flex min-w-0 list-none items-center p-0 sm:gap-1">
            {STEPS.map((label, index) => {
              const state = index < step ? 'done' : index === step ? 'current' : 'upcoming';
              return (
                <li key={label} className="flex items-center">
                  {index > 0 ? (
                    <span
                      className={cn(
                        'mx-2 h-px w-4 transition-colors sm:w-8',
                        index <= step ? 'bg-accent-border' : 'bg-well',
                      )}
                      aria-hidden
                    />
                  ) : null}
                  <span
                    aria-current={state === 'current' ? 'step' : undefined}
                    className="flex items-center gap-1.5"
                  >
                    <span
                      className={cn(
                        'text-2xs flex size-5 items-center justify-center rounded-full font-bold transition-colors',
                        state === 'current'
                          ? 'bg-accent text-accent-fg'
                          : state === 'done'
                            ? 'bg-success text-accent-fg'
                            : 'border-border-subtle bg-panel text-muted border',
                      )}
                    >
                      {state === 'done' ? (
                        <Check className="size-3" strokeWidth={3} aria-hidden />
                      ) : (
                        index + 1
                      )}
                    </span>
                    <span
                      className={cn(
                        'text-2xs hidden font-bold uppercase sm:inline',
                        state === 'current'
                          ? 'text-accent-text'
                          : state === 'done'
                            ? 'text-success-text'
                            : 'text-muted',
                      )}
                    >
                      {label}
                    </span>
                  </span>
                </li>
              );
            })}
          </ol>

          <span className="text-3xs border-border-subtle/60 bg-well text-muted ml-auto shrink-0 rounded-full border px-2 py-1 font-semibold sm:ml-0">
            Step {step + 1} of {STEPS.length}
          </span>
        </div>
      </header>

      {/* Step stage: cards center within the viewport leftover instead of
          stretching against it; review trades centering for fill width. */}
      <main
        className={cn(
          'flex flex-1 flex-col px-4 py-6 sm:justify-center sm:px-6 sm:py-8 lg:px-8',
          STEP_STAGE[step].stageAlign,
        )}
      >
        <div
          className={cn(
            'mx-auto flex w-full flex-col',
            STEP_STAGE[step].maxWidth,
            STEP_STAGE[step].centerY,
          )}
        >
          {step === 0 ? (
            <form
              noValidate
              onSubmit={submitBrand}
              className="bg-panel shadow-card rounded-2xl p-6 sm:p-8"
            >
              <div className="grid gap-6">
                <div className="grid gap-1.5">
                  <h1 className="font-display text-foreground text-2xl font-bold sm:text-3xl">
                    {isAdditional ? 'Add a project' : 'What brand are we tracking?'}
                  </h1>
                  <p className="text-muted text-sm">
                    We&apos;ll review your website, suggest comparable brands, and prepare balanced
                    questions.
                  </p>
                </div>

                <div className="grid gap-5 sm:grid-cols-2">
                  <Field
                    label="Brand name"
                    required
                    error={form.formState.errors.brand_name?.message}
                  >
                    {(props) => (
                      <Input {...props} {...form.register('brand_name')} placeholder="Acme" />
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
                      />
                    )}
                  </Field>
                  <Field
                    label="Industry"
                    hint="Optional — helps disambiguate similar names"
                    error={form.formState.errors.industry?.message}
                  >
                    {(props) => (
                      <Input
                        {...props}
                        {...form.register('industry')}
                        placeholder="Marketing analytics"
                      />
                    )}
                  </Field>
                  <Field label="Country" error={form.formState.errors.country_code?.message}>
                    {(props) => (
                      <Controller
                        control={form.control}
                        name="country_code"
                        render={({ field }) => (
                          <MarketSelect
                            {...props}
                            ariaLabel="Country"
                            value={field.value}
                            onChange={field.onChange}
                            onBlur={field.onBlur}
                            options={COUNTRY_OPTIONS}
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

                <div className="flex items-center gap-3">
                  <Button type="submit" className="font-semibold">
                    Continue
                  </Button>
                  {isAdditional ? (
                    <Button type="button" variant="ghost" onClick={() => router.push('/projects')}>
                      Cancel
                    </Button>
                  ) : null}
                </div>
              </div>
            </form>
          ) : null}

          {step === 1 ? (
            <div className="bg-panel shadow-card grid gap-6 rounded-2xl p-6 sm:p-8">
              <div className="grid gap-1.5">
                <h1 className="font-display text-foreground text-2xl font-bold sm:text-3xl">
                  Finding what to track
                </h1>
                <p className="text-muted text-sm">
                  We&apos;re learning about {brand?.brand_name || 'your brand'} and preparing useful
                  questions. You can review everything before the project is created.
                </p>
              </div>

              <div className="border-border-subtle bg-background/80 rounded-xl border p-5">
                <ActivityProgress
                  label="Discovering your brand"
                  steps={discoveryActivity(discovery.discovery)}
                />
              </div>

              {discovery.discovery?.status === 'needs_input' ? (
                <Alert tone="warning">
                  <div className="flex items-center justify-between gap-3">
                    <span>
                      Some details could not be confirmed. Retry, or review the useful results we
                      found and fill in anything that is missing.
                    </span>
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

              <div className="flex items-center gap-3">
                <Button
                  onClick={() => setStep(2)}
                  disabled={
                    discovery.isRunning ||
                    !discovery.discovery ||
                    discovery.discovery.prompt_suggestions.length === 0
                  }
                  className="font-semibold"
                >
                  {discovery.isRunning ? 'Searching…' : 'Review'}
                </Button>
                <Button variant="ghost" onClick={() => setStep(0)}>
                  Back
                </Button>
              </div>
            </div>
          ) : null}

          {step === 2 ? (
            <div className="bg-panel shadow-card flex h-full flex-col gap-6 rounded-2xl p-6 sm:p-8">
              <div className="grid gap-1.5">
                <h1 className="font-display text-foreground text-2xl font-bold sm:text-3xl">
                  Does this look right?
                </h1>
                <p className="text-muted text-sm">
                  Deselect anything you don&apos;t want — you can change all of it after setup.
                </p>
              </div>

              <ReviewStep
                domains={domains}
                competitors={competitors}
                prompts={prompts}
                onToggleDomain={toggle(setDomains)}
                onToggleCompetitor={(index) =>
                  setCompetitors((previous) => {
                    const selectedCount = previous.filter((item) => item.selected).length;
                    return previous.map((item, itemIndex) => {
                      if (itemIndex !== index) return item;
                      if (
                        !item.selected &&
                        (maximumCompetitors === undefined || selectedCount >= maximumCompetitors)
                      ) {
                        return item;
                      }
                      return { ...item, selected: !item.selected };
                    });
                  })
                }
                onTogglePrompt={toggle(setPrompts)}
                onRenameCompetitor={(index, name) =>
                  setCompetitors((prev) =>
                    prev.map((item, i) => (i === index ? { ...item, name } : item)),
                  )
                }
                onAddCompetitor={() =>
                  setCompetitors((prev) => {
                    const selectedCount = prev.filter((item) => item.selected).length;
                    if (maximumCompetitors === undefined || selectedCount >= maximumCompetitors) {
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

              {discovery.discovery?.profile.description ? (
                <div className="border-border-subtle bg-background/70 rounded-xl border p-4">
                  <p className="text-2xs text-muted font-bold uppercase">Discovered profile</p>
                  <p className="text-secondary mt-2 text-sm leading-relaxed">
                    {discovery.discovery.profile.description}
                  </p>
                </div>
              ) : null}

              {complete.isError ? (
                <Alert tone="danger">{onboardingErrorMessage(complete.error)}</Alert>
              ) : null}
              {!hasSelectedDomain || !hasSelectedPrompt ? (
                <Alert tone="warning">
                  Keep at least one website address and one starting question selected.
                </Alert>
              ) : null}
              {hasSelectedPrompt && !hasBalancedPromptPortfolio ? (
                <Alert tone="warning">
                  Keep at least four general questions selected for each named comparison.
                </Alert>
              ) : null}
              {hasSelectedPrompt && !comparisonsMatchSelectedCompetitors ? (
                <Alert tone="warning">
                  Deselect named comparisons for competitors you are not tracking.
                </Alert>
              ) : null}

              <div className="flex items-center gap-3 pt-2">
                <Button
                  onClick={() => complete.mutate()}
                  disabled={
                    complete.isPending ||
                    !hasSelectedDomain ||
                    !hasSelectedPrompt ||
                    !hasBalancedPromptPortfolio ||
                    !comparisonsMatchSelectedCompetitors
                  }
                  className="font-semibold"
                >
                  {complete.isPending ? 'Creating…' : 'Create project'}
                </Button>
                <Button variant="ghost" onClick={() => setStep(1)} disabled={complete.isPending}>
                  Back
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
}
