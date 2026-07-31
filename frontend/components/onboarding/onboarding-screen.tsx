'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { Controller, useForm, useWatch } from 'react-hook-form';
import { Check } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { LogoMark } from '@/components/ui/logo-mark';
import { MarketSelect } from '@/components/ui/market-select';
import { queryKeys } from '@/lib/api/query-keys';
import { projectsApi } from '@/lib/api/projects';
import {
  brandStepSchema,
  deriveDomain,
  emptyBrandStep,
  onboardingErrorMessage,
  type BrandStepValues,
  type ReviewCompetitor,
  type ReviewDomain,
  type ReviewPrompt,
} from '@/lib/onboarding/forms';
import {
  createProjectFromOnboarding,
  type OnboardingProgress,
} from '@/lib/onboarding/create-project';
import { useDiscovery } from '@/lib/onboarding/use-discovery';
import { useProjectContext } from '@/lib/project/project-context';
import { cn } from '@/lib/utils';
import { COUNTRY_OPTIONS, LANGUAGE_OPTIONS } from '@/lib/setup/markets';

import { DiscoveryProgress } from './discovery-progress';
import { ReviewStep } from './review-step';

/**
 * Onboarding — the only way a project gets created (plan.md §10, decision 11;
 * `/setup` is retired).
 *
 * Four steps: Brand → Discovery → Review → Finish, framed by a slim header
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
const STEPS = ['Brand', 'Discovery', 'Review', 'Finish'] as const;
type StepIndex = 0 | 1 | 2 | 3;

/**
 * Per-step stage geometry. The short form/progress/congrats steps are narrow
 * cards centered both ways; the data-dense review step is wide, top-aligned,
 * and flex-height so its internal columns fill the stage rather than scroll it.
 */
const STEP_STAGE: Record<StepIndex, { maxWidth: string; centerY: string; stageAlign: string }> = {
  0: { maxWidth: 'max-w-3xl', centerY: 'justify-center', stageAlign: 'sm:justify-center' },
  1: { maxWidth: 'max-w-3xl', centerY: 'justify-center', stageAlign: 'sm:justify-center' },
  2: { maxWidth: 'h-full max-w-5xl', centerY: '', stageAlign: '' },
  3: {
    maxWidth: 'max-w-lg',
    centerY: 'justify-center text-center',
    stageAlign: 'sm:justify-center',
  },
};

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

  const [step, setStep] = useState<StepIndex>(0);
  const [brand, setBrand] = useState<BrandStepValues | null>(null);
  const [domains, setDomains] = useState<ReviewDomain[]>([]);
  const [competitors, setCompetitors] = useState<ReviewCompetitor[]>([]);
  const [prompts, setPrompts] = useState<ReviewPrompt[]>([]);
  const [createdProjectName, setCreatedProjectName] = useState<string | null>(null);
  const [createdProgress, setCreatedProgress] = useState<OnboardingProgress>({});

  const form = useForm<BrandStepValues>({
    resolver: zodResolver(brandStepSchema),
    defaultValues: emptyBrandStep,
  });

  const discovery = useDiscovery(step >= 1 ? brand : null);
  const websiteUrl = useWatch({ control: form.control, name: 'website_url' });
  const derivedDomain = deriveDomain(websiteUrl);

  // Seed the editable review lists once each section lands. Guarded on length
  // so re-renders never clobber the user's selections mid-review.
  const { state: discoveryState } = discovery;
  useEffect(() => {
    if (discoveryState.domains.status === 'done') {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- seed editable state from a completed discovery result.
      setDomains((prev) =>
        prev.length > 0
          ? prev
          : discoveryState.domains.data.map((domain, index) => ({
              id: `domain:${index}:${domain}`,
              domain,
              selected: true,
            })),
      );
    }
  }, [discoveryState.domains]);

  useEffect(() => {
    if (discoveryState.competitors.status === 'done') {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- seed editable state from a completed discovery result.
      setCompetitors((prev) =>
        prev.length > 0
          ? prev
          : discoveryState.competitors.data.map((competitor, index) => ({
              ...competitor,
              id: `competitor:${index}:${competitor.name}`,
              selected: true,
            })),
      );
    }
  }, [discoveryState.competitors]);

  useEffect(() => {
    if (discoveryState.prompts.status === 'done') {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- seed editable state from a completed discovery result.
      setPrompts((prev) =>
        prev.length > 0
          ? prev
          : discoveryState.prompts.data.map((prompt, index) => ({
              ...prompt,
              id: `prompt:${index}:${prompt.text}`,
              selected: true,
            })),
      );
    }
  }, [discoveryState.prompts]);

  // Survives a failed confirm so "Create project" retries the writes that failed
  // instead of creating a second project. Cleared only when the brand changes
  // (see submitBrand) — that is a different project, not a retry.
  const confirm = useMutation({
    mutationFn: () => {
      if (!brand) throw new Error('Brand details are missing.');
      return createProjectFromOnboarding({
        brand,
        competitors,
        domains,
        prompts,
        progress: createdProgress,
      });
    },
    onSuccess: async (project) => {
      setActiveProjectId(project.id);
      // Logo hydration is best-effort and never blocks onboarding. The backend
      // checks its database cache before crawling; once it finishes, refresh
      // the project list so every shared BrandLogo instance updates together.
      void projectsApi
        .refreshProjectLogos(project.id)
        .then(() => queryClient.invalidateQueries({ queryKey: queryKeys.projects.list() }))
        .catch(() => undefined);
      // Refresh before showing the completion screen, so the dashboard is ready
      // as soon as the user leaves onboarding.
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects.list() });
      setCreatedProjectName(project.name);
      setStep(3);
    },
  });

  const submitBrand = form.handleSubmit((values) => {
    // Correcting the brand starts a NEW discovery run, so the review lists must
    // be emptied first: the seeding effects bail out when `prev.length > 0` and
    // would otherwise leave the previous brand's results standing in front of
    // the new ones. Keyed on the same brand_name|website_url pair useDiscovery
    // re-fires on — Back → Continue with the values unchanged re-runs nothing,
    // so clearing there would blank the review step for good.
    const rediscovers =
      brand !== null &&
      (brand.brand_name !== values.brand_name || brand.website_url !== values.website_url);
    if (rediscovers) {
      setDomains([]);
      setCompetitors([]);
      setPrompts([]);
      // A different brand is a fresh creation, not a retry of the last confirm.
      setCreatedProgress({});
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
    <div className="bg-background text-foreground selection:bg-accent relative flex min-h-dvh flex-col antialiased selection:text-white">
      {/* Background ambient lighting */}
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="bg-accent-subtle/40 absolute -top-40 -left-40 size-[500px] rounded-full blur-[120px]" />
        <div className="bg-accent-subtle/40 absolute -right-40 -bottom-40 size-[500px] rounded-full blur-[120px]" />
      </div>

      {/* Opaque surface, no blur: the elevation guard (design.md §4a) keeps
          gradients and blur to display art, never a control container. */}
      <header className="border-border-subtle/80 border-b bg-white py-3">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 sm:gap-6 sm:px-6 lg:px-8">
          <span className="flex shrink-0 items-center gap-2">
            <LogoMark size={24} />
            <span className="font-mkt-display text-foreground text-base font-bold">Searchify</span>
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
                          ? 'bg-accent text-white'
                          : state === 'done'
                            ? 'bg-success text-white'
                            : 'border-border-subtle text-muted border bg-white',
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
              className="shadow-card border-border-subtle rounded-2xl border bg-white p-6 sm:p-8"
            >
              <div className="grid gap-6">
                <div className="grid gap-1.5">
                  <h1 className="font-mkt-display text-foreground text-2xl font-bold sm:text-3xl">
                    {isAdditional ? 'Add a project' : 'What brand are we tracking?'}
                  </h1>
                  <p className="text-muted text-sm">
                    We&apos;ll discover your domains, competitors and starting prompts from this.
                  </p>
                </div>

                <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start">
                  {/* Identity column: the two fields the discovery keys on. */}
                  <div className="grid gap-5">
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
                          className="border-border-subtle bg-background/80 text-foreground placeholder:text-muted focus:bg-white"
                        />
                      )}
                    </Field>

                    <Field
                      label="Website"
                      required
                      error={form.formState.errors.website_url?.message}
                      hint={derivedDomain ? `We'll track ${derivedDomain}` : undefined}
                    >
                      {(props) => (
                        <Input
                          {...props}
                          {...form.register('website_url')}
                          placeholder="acme.com"
                          className="border-border-subtle bg-background/80 text-foreground placeholder:text-muted focus:bg-white"
                        />
                      )}
                    </Field>
                  </div>

                  {/* Context column: the readonly summary tile fills what was
                      dead air next to the two inputs; the subtle slate keeps it
                      clearly non-interactive while balancing the height. */}
                  <div className="border-border-subtle bg-background/80 rounded-xl border px-5 py-5">
                    <p className="text-2xs text-muted font-bold uppercase">
                      Here&apos;s what we&apos;ll set up
                    </p>
                    <ul className="mt-3 grid gap-2">
                      {[
                        'Crawl your site to discover owned domains',
                        'Identify the competitors AI engines compare you to',
                        'Generate starting buyer prompts to track',
                      ].map((item) => (
                        <li key={item} className="text-secondary flex items-start gap-2 text-sm">
                          <Check
                            className="text-accent-text mt-0.5 size-4 shrink-0"
                            strokeWidth={2.5}
                            aria-hidden
                          />
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* Market row spans back under both columns so the card reads
                      wide instead of leaving a lone field pair beside the tile. */}
                  <div className="grid gap-5 sm:grid-cols-2 lg:col-span-2">
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
            <div className="shadow-card border-border-subtle grid gap-5 rounded-2xl border bg-white p-6 sm:p-8">
              <div className="grid gap-1.5">
                <h1 className="font-mkt-display text-foreground text-2xl font-bold sm:text-3xl">
                  Finding what to track
                </h1>
                <p className="text-muted text-sm">
                  Three searches run in parallel for {brand?.brand_name || 'your brand'}.
                </p>
              </div>

              <DiscoveryProgress state={discovery.state} onRetry={discovery.retry} />

              {discovery.agentUnconfigured ? (
                <Alert tone="warning">
                  AI discovery is unavailable. You can continue and add competitors and prompts
                  yourself.
                </Alert>
              ) : null}

              <div className="flex items-center gap-3">
                <Button
                  onClick={() => setStep(2)}
                  disabled={discovery.isRunning}
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
            <div className="shadow-card border-border-subtle flex h-full flex-col gap-6 rounded-2xl border bg-white p-6 sm:p-8">
              <div className="grid gap-1.5">
                <h1 className="font-mkt-display text-foreground text-2xl font-bold sm:text-3xl">
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
                onToggleCompetitor={toggle(setCompetitors)}
                onTogglePrompt={toggle(setPrompts)}
                onRenameCompetitor={(index, name) =>
                  setCompetitors((prev) =>
                    prev.map((item, i) => (i === index ? { ...item, name } : item)),
                  )
                }
                onAddCompetitor={() =>
                  setCompetitors((prev) => [
                    ...prev,
                    {
                      id: `competitor:manual:${manualCompetitorId()}`,
                      name: '',
                      domains: [],
                      selected: true,
                    },
                  ])
                }
              />

              {confirm.isError ? (
                <Alert tone="danger">{onboardingErrorMessage(confirm.error)}</Alert>
              ) : null}

              <div className="flex items-center gap-3 pt-2">
                <Button
                  onClick={() => confirm.mutate()}
                  disabled={confirm.isPending}
                  className="font-semibold"
                >
                  {confirm.isPending ? 'Creating…' : 'Create project'}
                </Button>
                <Button variant="ghost" onClick={() => setStep(1)} disabled={confirm.isPending}>
                  Back
                </Button>
              </div>
            </div>
          ) : null}

          {step === 3 ? (
            <div className="shadow-card border-border-subtle grid justify-items-center gap-6 rounded-2xl border bg-white p-8 text-center sm:p-10">
              <div className="grid justify-items-center gap-2">
                <div className="bg-success-bg text-success-text mb-2 inline-flex size-12 items-center justify-center rounded-2xl">
                  <Check className="size-6" strokeWidth={2.5} aria-hidden />
                </div>
                <h1 className="font-mkt-display text-foreground text-2xl font-bold sm:text-3xl">
                  Your workspace is ready
                </h1>
                <p className="text-muted text-sm leading-relaxed">
                  {createdProjectName ?? 'Your project'} is set up. We&apos;ve queued a free Site
                  Health crawl in the background; its status and results will appear on your
                  dashboard.
                </p>
              </div>
              <div className="pt-2">
                <Button onClick={() => router.replace('/projects')} className="font-semibold">
                  Open dashboard
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
}
