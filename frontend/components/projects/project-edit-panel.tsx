'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, X } from 'lucide-react';
import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { MarketSelect } from '@/components/ui/market-select';
import { projectsApi } from '@/lib/api/projects';
import { brandDiscoveriesApi } from '@/lib/api/brand-discoveries';
import { queryKeys } from '@/lib/api/query-keys';
import type { Project } from '@/lib/api/types';
import { onboardingErrorMessage } from '@/lib/onboarding/forms';
import { COUNTRY_OPTIONS, LANGUAGE_OPTIONS } from '@/lib/setup/markets';

/**
 * Edit an existing project's configuration.
 *
 * Onboarding replaced `/setup` and owns *creation*; this owns everything
 * afterwards. Without it, a brand's website, competitors and domains were fixed
 * at whatever discovery produced on day one — the gap left by retiring the
 * setup edit form.
 *
 * Deliberately a flat panel, not a stepper. The old edit surface was a
 * five-step wizard, which is the wrong shape for changing one alias: a wizard
 * is for a task you do once, a panel is for a thing you keep. Everything is
 * visible at once and Save sends only what changed.
 *
 * Comma-separated text for the list fields rather than per-row editors. These
 * are short lists of short strings, and a row-with-remove-button UI for
 * aliases was a meaningful chunk of the old form's weight for no real gain.
 */
const splitList = (value: string): string[] =>
  value
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);

/**
 * Draft rows carry a stable `key` because the list is editable AND removable.
 * Keyed by array index, removing the first of three rows shifted every row's
 * identity: React reused the same DOM inputs for different competitors, so
 * focus, selection, and any in-flight IME composition landed on the wrong row.
 * The counter is module-scoped and monotonic — it only has to be unique within
 * one mounted list, never persisted or sent to the backend.
 */
let competitorKeySeq = 0;
const nextCompetitorKey = () => `competitor-${(competitorKeySeq += 1)}`;

type CompetitorDraft = { key: string; name: string; domains: string };

export function ProjectEditPanel({
  project,
  open,
  onOpenChange,
}: Readonly<{ project: Project; open: boolean; onOpenChange: (open: boolean) => void }>) {
  const queryClient = useQueryClient();
  const discoveryCatalog = useQuery({
    queryKey: ['brand-discovery-catalog'],
    queryFn: ({ signal }) => brandDiscoveriesApi.catalog({ signal }),
    enabled: open,
    staleTime: Number.POSITIVE_INFINITY,
  });

  const [brandName, setBrandName] = useState(project.brand_name);
  const [websiteUrl, setWebsiteUrl] = useState(project.website_url);
  const [country, setCountry] = useState(project.country_code);
  const [language, setLanguage] = useState(project.language_code);
  // Lazy initializers: these join/map the project's arrays, and a bare
  // `useState(expr)` re-runs `expr` on every keystroke in this panel only to
  // throw the result away.
  const [aliases, setAliases] = useState(() => project.brand.aliases.join(', '));
  const [ownedDomains, setOwnedDomains] = useState(() => project.owned_domains.join(', '));
  const [unintendedDomains, setUnintendedDomains] = useState(() =>
    project.unintended_domains.join(', '),
  );
  const [competitors, setCompetitors] = useState<CompetitorDraft[]>(() =>
    project.competitors.map((competitor) => ({
      key: nextCompetitorKey(),
      name: competitor.name,
      domains: competitor.domains.join(', '),
    })),
  );
  const maximumCompetitors = discoveryCatalog.data?.maximum_competitors;
  const competitorLimitReached =
    maximumCompetitors === undefined || competitors.length >= maximumCompetitors;

  const save = useMutation({
    mutationFn: () =>
      projectsApi.updateProject(project.id, {
        brand_name: brandName.trim(),
        website_url: websiteUrl.trim(),
        country_code: country.trim().toUpperCase(),
        language_code: language.trim(),
        brand: { aliases: splitList(aliases) },
        owned_domains: splitList(ownedDomains),
        unintended_domains: splitList(unintendedDomains),
        competitors: competitors.flatMap((competitor) => {
          const name = competitor.name.trim();
          return name
            ? [
                {
                  name,
                  // Aliases are not edited here — preserve whatever the project
                  // already had rather than silently clearing them on every save.
                  aliases:
                    project.competitors.find((existing) => existing.name === competitor.name)
                      ?.aliases ?? [],
                  domains: splitList(competitor.domains),
                },
              ]
            : [];
        }),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects.list() });
      onOpenChange(false);
    },
  });

  const updateCompetitor = (index: number, patch: Partial<CompetitorDraft>) =>
    setCompetitors((prev) =>
      prev.map((competitor, i) => (i === index ? { ...competitor, ...patch } : competitor)),
    );

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Edit ${project.brand_name || project.name}`}
      description="Changes apply to future audits. Existing results keep the settings they ran with."
      className="w-155"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={save.isPending}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </>
      }
    >
      <div className="max-h-dialog-scroll grid gap-[var(--workspace-gap)] overflow-y-auto pe-1">
        {save.isError ? <Alert tone="danger">{onboardingErrorMessage(save.error)}</Alert> : null}

        <div className="grid gap-4">
          <Field label="Brand name">
            {(props) => (
              <Input
                {...props}
                value={brandName}
                onChange={(event) => setBrandName(event.target.value)}
              />
            )}
          </Field>
          <Field label="Website">
            {(props) => (
              <Input
                {...props}
                value={websiteUrl}
                onChange={(event) => setWebsiteUrl(event.target.value)}
              />
            )}
          </Field>
          <Field label="Brand aliases" hint="Comma separated">
            {(props) => (
              <Input
                {...props}
                value={aliases}
                onChange={(event) => setAliases(event.target.value)}
                placeholder="Acme Inc, Acme Co"
              />
            )}
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Country">
              {(props) => (
                <MarketSelect
                  {...props}
                  ariaLabel="Country"
                  value={country}
                  onChange={setCountry}
                  options={COUNTRY_OPTIONS}
                />
              )}
            </Field>
            <Field label="Language">
              {(props) => (
                <MarketSelect
                  {...props}
                  ariaLabel="Language"
                  value={language}
                  onChange={setLanguage}
                  options={LANGUAGE_OPTIONS}
                />
              )}
            </Field>
          </div>
        </div>

        <div className="grid gap-4">
          <p className={eyebrowClasses}>Domains</p>
          <Field label="Owned" hint="Comma separated">
            {(props) => (
              <Input
                {...props}
                value={ownedDomains}
                onChange={(event) => setOwnedDomains(event.target.value)}
                placeholder="acme.com, shop.acme.com"
              />
            )}
          </Field>
          <Field label="Unintended" hint="Domains that are not yours but get confused for you">
            {(props) => (
              <Input
                {...props}
                value={unintendedDomains}
                onChange={(event) => setUnintendedDomains(event.target.value)}
              />
            )}
          </Field>
        </div>

        <div className="grid gap-2">
          <div className="flex items-center gap-2">
            <p className={eyebrowClasses}>Competitors</p>
            <span className="text-muted text-xs">
              {competitors.length} of {maximumCompetitors ?? '…'}
            </span>
            <Button
              variant="ghost"
              size="sm"
              className="ms-auto"
              aria-label="Add competitor"
              disabled={competitorLimitReached}
              onClick={() =>
                setCompetitors((prev) => [
                  ...prev,
                  { key: nextCompetitorKey(), name: '', domains: '' },
                ])
              }
            >
              <Plus className="size-4" aria-hidden />
              Add
            </Button>
          </div>
          {competitors.length === 0 ? (
            <p className="text-muted text-sm">None tracked.</p>
          ) : (
            <ul className="grid list-none gap-2 p-0">
              {competitors.map((competitor, index) => (
                <li key={competitor.key} className="flex items-center gap-2">
                  <Input
                    value={competitor.name}
                    onChange={(event) => updateCompetitor(index, { name: event.target.value })}
                    aria-label={`Competitor ${index + 1} name`}
                    placeholder="Name"
                  />
                  <Input
                    value={competitor.domains}
                    onChange={(event) => updateCompetitor(index, { domains: event.target.value })}
                    aria-label={`Competitor ${index + 1} domains`}
                    placeholder="Domains"
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove ${competitor.name || `competitor ${index + 1}`}`}
                    onClick={() => setCompetitors((prev) => prev.filter((_, i) => i !== index))}
                  >
                    <X className="size-4" aria-hidden />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Dialog>
  );
}
