'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Save } from 'lucide-react';
import { useState, type ReactNode } from 'react';

import { Alert } from '@/components/ui/alert';
import { BrandLogo } from '@/components/ui/brand-logo';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Textarea } from '@/components/ui/textarea';
import { TabPanel, Tabs } from '@/components/ui/tabs';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import { projectsApi } from '@/lib/api/projects';
import { queryKeys } from '@/lib/api/query-keys';
import type { BrandProfile, BrandProfileDraft, Project } from '@/lib/api/types';
import { formErrorMessage } from '@/lib/forms/error-message';

const PROFILE_TABS = [
  { id: 'facts', label: 'Facts & Positioning' },
  { id: 'audience', label: 'Audience & Offerings' },
  { id: 'competitors', label: 'Competitors' },
] as const;

type ProfileTab = (typeof PROFILE_TABS)[number]['id'];
type TrackedCompetitor = Pick<Project['competitors'][number], 'name' | 'logo_url' | 'domains'>;

function profileDraft(profile: BrandProfile): BrandProfileDraft {
  return {
    description: profile.description,
    positioning: profile.positioning,
    products_services: profile.products_services,
    target_audience: profile.target_audience,
  };
}

function parseProductsInput(value: string): string[] {
  return value.split(',').flatMap((item) => {
    const trimmed = item.trim();
    return trimmed ? [trimmed] : [];
  });
}

export function BrandProfilePanel({
  projectId,
  profile,
  competitors = [],
  competitorSuggestions,
  onSaved,
}: Readonly<{
  projectId: string;
  profile: BrandProfile;
  competitors?: readonly TrackedCompetitor[];
  competitorSuggestions?: ReactNode;
  onSaved?: () => void;
}>) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => profileDraft(profile));
  const [productsInput, setProductsInput] = useState(() => profile.products_services.join(', '));
  const [notice, setNotice] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ProfileTab>('facts');

  const saveMutation = useMutation({
    mutationFn: () =>
      projectsApi.updateBrandProfile(projectId, {
        ...draft,
        products_services: parseProductsInput(productsInput),
      }),
    onSuccess: (next) => {
      queryClient.setQueryData(queryKeys.projects.brandProfile(projectId), next);
      onSaved?.();
      setDraft(profileDraft(next));
      setProductsInput(next.products_services.join(', '));
      setNotice('Brand knowledge saved. These details now inform assisted features.');
    },
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        <Button
          variant="primary"
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
        >
          <Save className="size-4" aria-hidden />
          {saveMutation.isPending ? 'Saving…' : 'Save brand knowledge'}
        </Button>
      </div>

      {saveMutation.error ? (
        <Alert tone="danger">{formErrorMessage(saveMutation.error)}</Alert>
      ) : null}
      {notice ? <Alert tone="success">{notice}</Alert> : null}

      <Tabs
        value={activeTab}
        onValueChange={setActiveTab}
        items={PROFILE_TABS.map((tab) => ({ value: tab.id, label: tab.label }))}
        ariaLabel="Company facts sections"
        rootClassName="grid gap-4"
      >
        <TabPanel value={activeTab} className="focus-ring">
          <ProfileTabPanel
            activeTab={activeTab}
            draft={draft}
            productsInput={productsInput}
            disabled={saveMutation.isPending}
            competitors={competitors}
            competitorSuggestions={competitorSuggestions}
            onDraftChange={setDraft}
            onProductsChange={setProductsInput}
          />
        </TabPanel>
      </Tabs>
    </div>
  );
}

function ProfileTabPanel({
  activeTab,
  draft,
  productsInput,
  disabled,
  competitors,
  competitorSuggestions,
  onDraftChange,
  onProductsChange,
}: Readonly<{
  activeTab: ProfileTab;
  draft: BrandProfileDraft;
  productsInput: string;
  disabled: boolean;
  competitors: readonly TrackedCompetitor[];
  competitorSuggestions?: ReactNode;
  onDraftChange: (draft: BrandProfileDraft) => void;
  onProductsChange: (value: string) => void;
}>) {
  if (activeTab === 'facts') {
    return (
      <div className="grid gap-[var(--workspace-gap)]">
        <Field label="Description" hint="Core mission, value proposition, and brand summary.">
          {(field) => (
            <Textarea
              {...field}
              rows={6}
              disabled={disabled}
              value={draft.description}
              onChange={(event) => onDraftChange({ ...draft, description: event.target.value })}
            />
          )}
        </Field>
        <Field
          label="Positioning"
          hint="Include price tier, differentiation, and competitive segment."
        >
          {(field) => (
            <Textarea
              {...field}
              rows={6}
              disabled={disabled}
              value={draft.positioning}
              onChange={(event) => onDraftChange({ ...draft, positioning: event.target.value })}
            />
          )}
        </Field>
      </div>
    );
  }

  if (activeTab === 'audience') {
    return (
      <div className="grid gap-[var(--workspace-gap)]">
        <Field
          label="Target audience"
          hint="Key demographics, customer personas, and ideal buyers."
        >
          {(field) => (
            <Textarea
              {...field}
              rows={6}
              disabled={disabled}
              value={draft.target_audience}
              onChange={(event) => onDraftChange({ ...draft, target_audience: event.target.value })}
            />
          )}
        </Field>
        <Field label="Products and services" hint="Comma-separated category labels.">
          {(field) => (
            <Textarea
              {...field}
              rows={6}
              disabled={disabled}
              value={productsInput}
              onChange={(event) => onProductsChange(event.target.value)}
            />
          )}
        </Field>
      </div>
    );
  }

  return (
    <div className="grid gap-[var(--workspace-gap)]">
      <section aria-labelledby="tracked-competitors" className="grid gap-2">
        <h3 id="tracked-competitors" className="text-foreground text-sm font-semibold">
          Tracked competitors
        </h3>
        {competitors.length ? (
          <ul className="grid gap-2 sm:grid-cols-2">
            {competitors.map((competitor) => (
              <li
                key={`${competitor.name}:${competitor.domains[0] ?? ''}`}
                className="bg-background text-secondary flex min-w-0 items-center gap-2 rounded-[var(--radius-control)] px-3 py-2 text-xs font-medium"
              >
                <BrandLogo
                  name={competitor.name}
                  logoUrl={competitor.logo_url}
                  websiteUrl={competitor.domains[0]}
                  size="sm"
                />
                <span className="truncate">{competitor.name}</span>
              </li>
            ))}
          </ul>
        ) : (
          <UnavailableValue state="not_set" />
        )}
      </section>
      {competitorSuggestions}
    </div>
  );
}
