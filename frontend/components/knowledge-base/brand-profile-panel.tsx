'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Save } from 'lucide-react';
import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardEyebrow, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Textarea } from '@/components/ui/input';
import { projectsApi } from '@/lib/api/projects';
import { queryKeys } from '@/lib/api/query-keys';
import type { BrandProfile, BrandProfileDraft } from '@/lib/api/types';
import { formErrorMessage } from '@/lib/forms/error-message';

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
}: Readonly<{
  projectId: string;
  profile: BrandProfile;
}>) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => profileDraft(profile));
  const [productsInput, setProductsInput] = useState(profile.products_services.join(', '));
  const [notice, setNotice] = useState<string | null>(null);

  const saveMutation = useMutation({
    mutationFn: () =>
      projectsApi.updateBrandProfile(projectId, {
        ...draft,
        products_services: parseProductsInput(productsInput),
      }),
    onSuccess: (next) => {
      queryClient.setQueryData(queryKeys.projects.brandProfile(projectId), next);
      setDraft(profileDraft(next));
      setProductsInput(next.products_services.join(', '));
      setNotice('Brand knowledge saved. These details now inform assisted features.');
    },
  });

  return (
    <Card aria-labelledby="brand-knowledge-title">
      <CardHeader>
        <div className="grid gap-1">
          <CardEyebrow>Brand profile</CardEyebrow>
          <CardTitle id="brand-knowledge-title">Facts & positioning</CardTitle>
          <p className="text-secondary text-sm">
            Curated context used by competitor and prompt generation. Derived site facts are
            corrected inline in Site Intelligence; generated prose never becomes knowledge.
          </p>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4">
        {saveMutation.error ? (
          <Alert tone="danger">{formErrorMessage(saveMutation.error)}</Alert>
        ) : null}
        {notice ? <Alert tone="success">{notice}</Alert> : null}

        <div className="grid gap-4 lg:grid-cols-2">
          <Field label="Description" hint="Core mission, value proposition, and brand summary.">
            {(field) => (
              <Textarea
                {...field}
                rows={3}
                disabled={saveMutation.isPending}
                value={draft.description}
                onChange={(event) => setDraft({ ...draft, description: event.target.value })}
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
                rows={3}
                disabled={saveMutation.isPending}
                value={draft.positioning}
                onChange={(event) => setDraft({ ...draft, positioning: event.target.value })}
              />
            )}
          </Field>
          <Field
            label="Target audience"
            hint="Key demographics, customer personas, and ideal buyers."
          >
            {(field) => (
              <Textarea
                {...field}
                rows={3}
                disabled={saveMutation.isPending}
                value={draft.target_audience}
                onChange={(event) => setDraft({ ...draft, target_audience: event.target.value })}
              />
            )}
          </Field>
          <Field label="Products and services" hint="Comma-separated category labels.">
            {(field) => (
              <Textarea
                {...field}
                rows={3}
                disabled={saveMutation.isPending}
                value={productsInput}
                onChange={(event) => setProductsInput(event.target.value)}
              />
            )}
          </Field>
        </div>

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
      </CardContent>
    </Card>
  );
}
