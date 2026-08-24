'use client';

import Link from 'next/link';
import { PackageSearch, Play, Sparkles } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { httpErrorStatus } from '@/lib/api/errors';
import { categoryIdentity, formatAvgRank, formatPercent } from '@/lib/products/catalog';
import type { ProductsTab } from '@/lib/products/catalog';
import type { useCommerceOverview } from '@/lib/products/use-products-screen';

type OverviewQueries = ReturnType<typeof useCommerceOverview>;

function catalogGate(queries: OverviewQueries, onSelectTab: (tab: ProductsTab) => void) {
  if (queries.visibilityQuery.isLoading || queries.productsQuery.isLoading) {
    return <p className="text-secondary text-sm">Loading Commerce overview…</p>;
  }
  if (queries.productsQuery.isError) {
    return <Alert tone="danger">Could not load the Commerce overview.</Alert>;
  }
  if (queries.productsQuery.data?.length) return null;
  return (
    <EmptyState
      icon={PackageSearch}
      heading="Add products before measuring Commerce visibility"
      description="Import the sample catalog or add the products you want CiteLadder to track."
      action={
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => onSelectTab('catalog')}>Import CSV</Button>
          <Button variant="secondary" asChild>
            <a href="/samples/commerce-products.csv" download>
              Download sample CSV
            </a>
          </Button>
        </div>
      }
    />
  );
}

function activeCommercePrompts(queries: OverviewQueries) {
  return (
    queries.commercePromptSet?.prompts.filter(
      (prompt) => prompt.cohort === 'commerce' && prompt.status === 'active',
    ) ?? []
  );
}

function categoryPromptsAreComplete(
  category: string,
  queries: OverviewQueries,
  prompts: ReturnType<typeof activeCommercePrompts>,
) {
  const topic = (queries.topicsQuery.data ?? []).find(
    (item) => categoryIdentity(item.name) === categoryIdentity(category),
  );
  if (!topic) return false;
  const intents = new Set(
    prompts.filter((prompt) => prompt.topic_id === topic.id).map((prompt) => prompt.intent),
  );
  return intents.has('discovery') && intents.has('comparison');
}

function promptsAreComplete(queries: OverviewQueries) {
  const prompts = activeCommercePrompts(queries);
  return queries.categories.every((category) =>
    categoryPromptsAreComplete(category, queries, prompts),
  );
}

function PromptSetup({ queries }: Readonly<{ queries: OverviewQueries }>) {
  return (
    <div className="grid gap-4">
      {queries.missingCategorySkus.length ? (
        <Alert tone="warning">
          Add a category for these SKUs before generating prompts:{' '}
          {queries.missingCategorySkus.join(', ')}.
        </Alert>
      ) : null}
      <EmptyState
        icon={Sparkles}
        heading="Generate product visibility prompts"
        description={`Create one buyer-discovery and one product comparison prompt for each of ${queries.categories.length} catalog categories.`}
        action={
          <Button
            onClick={() => queries.generatePromptsMutation.mutate({})}
            disabled={
              queries.generatePromptsMutation.isPending || queries.missingCategorySkus.length > 0
            }
          >
            {queries.generatePromptsMutation.isPending
              ? 'Generating by category…'
              : 'Generate prompts'}
          </Button>
        }
      />
      {queries.generatePromptsMutation.isError ? (
        <Alert tone="danger">
          {queries.generatePromptsMutation.error instanceof Error
            ? queries.generatePromptsMutation.error.message
            : 'Prompt generation failed.'}
        </Alert>
      ) : null}
    </div>
  );
}

function activeCommerceAudit(queries: OverviewQueries) {
  const activeStatuses = new Set([
    'draft',
    'validating',
    'queued',
    'running',
    'analyzing',
    'reporting',
  ]);
  return queries.commerceAudits.find((audit) => activeStatuses.has(audit.status));
}

export function CommerceOverviewPanel({
  queries,
  onSelectTab,
  onLaunchAudit,
}: Readonly<{
  queries: OverviewQueries;
  onSelectTab: (tab: ProductsTab) => void;
  onLaunchAudit: () => void;
}>) {
  const initialState = catalogGate(queries, onSelectTab);
  if (initialState) return initialState;
  if (queries.missingCategorySkus.length || !promptsAreComplete(queries)) {
    return <PromptSetup queries={queries} />;
  }
  const activeAudit = activeCommerceAudit(queries);
  if (activeAudit) {
    return (
      <EmptyState
        icon={Play}
        heading="Commerce audit in progress"
        description="The audit is measuring the catalog prompts across the selected engines."
        action={
          <Button asChild>
            <Link href={`/runs/${activeAudit.id}`}>View run</Link>
          </Button>
        }
      />
    );
  }
  if (queries.visibilityQuery.isError && httpErrorStatus(queries.visibilityQuery.error) !== 404) {
    return <Alert tone="danger">Could not load the Commerce overview.</Alert>;
  }
  if (
    (queries.visibilityQuery.isError && httpErrorStatus(queries.visibilityQuery.error) === 404) ||
    !queries.visibilityQuery.data
  ) {
    return (
      <EmptyState
        icon={Play}
        heading="Run your first Commerce visibility audit"
        description="Review the generated category prompts, then launch the citation-capable Commerce audit."
        action={<Button onClick={onLaunchAudit}>Launch Commerce audit</Button>}
      />
    );
  }
  const visibility = queries.visibilityQuery.data;
  const summary = visibility.summary;
  const gaps = [...visibility.products]
    .filter((product) => product.visibility_delta !== null)
    .sort((a, b) => a.visibility_delta! - b.visibility_delta!)
    .slice(0, 3);

  return (
    <div className="grid gap-4" data-testid="commerce-overview-panel">
      <CommercePrompts queries={queries} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi
          label="Products visible"
          value={`${summary.products_visible}/${summary.products_tracked}`}
        />
        <Kpi label="Visibility rate" value={formatPercent(summary.visibility_rate)} />
        <Kpi label="Top-three rate" value={formatPercent(summary.top_three_rate)} />
        <Kpi label="Average rank" value={formatAvgRank(summary.average_rank)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Engine visibility</CardTitle>
            <CardDescription>Latest completed audit across configured AI engines.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm">
            <p>{visibility.total_analyses} responses analyzed</p>
            <p>{summary.products_visible} uploaded products observed</p>
            <button
              className="text-link w-fit"
              type="button"
              onClick={() => onSelectTab('visibility')}
            >
              View AI Visibility
            </button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Largest product gaps</CardTitle>
            <CardDescription>Products with the weakest recent visibility movement.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm">
            {gaps.map((product) => (
              <Link
                key={product.product_id ?? product.sku}
                className="hover:bg-surface-hover flex justify-between rounded-sm p-2"
                href={
                  product.product_id ? `/products/${product.product_id}` : '/products?tab=catalog'
                }
              >
                <span>{product.name}</span>
                <span>{formatPercent(product.visibility_delta)}</span>
              </Link>
            ))}
            {!gaps.length ? <p className="text-muted">No product gaps yet.</p> : null}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recommended actions</CardTitle>
          <CardDescription>Deterministic opportunities tied to product evidence.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm">
          <RecommendedActions query={queries.opportunitiesQuery} onSelectTab={onSelectTab} />
        </CardContent>
      </Card>
    </div>
  );
}

function CommercePrompts({ queries }: Readonly<{ queries: OverviewQueries }>) {
  const prompts =
    queries.commercePromptSet?.prompts.filter((prompt) => prompt.cohort === 'commerce') ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Commerce Product Visibility prompts</CardTitle>
        <CardDescription>
          Read-only prompts generated from authoritative catalog categories.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {queries.categories.map((category) => {
          const topic = queries.topicsQuery.data?.find((item) => item.name === category);
          const rows = prompts.filter((prompt) => prompt.topic_id === topic?.id);
          return (
            <div key={category} className="grid gap-1">
              <strong className="text-sm">{category}</strong>
              {rows.map((prompt) => (
                <p key={prompt.id} className="text-secondary text-sm">
                  {prompt.text}
                </p>
              ))}
            </div>
          );
        })}
        <div>
          <Button
            variant="secondary"
            onClick={() => queries.generatePromptsMutation.mutate({ regenerate: true })}
            disabled={queries.generatePromptsMutation.isPending}
          >
            Regenerate
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function RecommendedActions({
  query,
  onSelectTab,
}: Readonly<{
  query: OverviewQueries['opportunitiesQuery'];
  onSelectTab: (tab: ProductsTab) => void;
}>) {
  // Loading and failure are answered before absence: an unresolved or failed
  // request carries no items, and reporting that as "no open actions" would
  // state a fact about the catalog that was never observed.
  if (query.isLoading) return <p className="text-secondary">Loading Commerce actions…</p>;
  if (query.isError) return <Alert tone="danger">Could not load Commerce actions.</Alert>;
  if (!query.data) return <p className="text-muted">Commerce actions are unavailable.</p>;
  const opportunities = query.data.items;
  if (!opportunities.length) return <p className="text-muted">No open Commerce actions.</p>;
  return (
    <>
      {opportunities.slice(0, 3).map((opportunity) => (
        <button
          key={opportunity.id}
          className="hover:bg-surface-hover flex justify-between rounded-sm p-2 text-left"
          type="button"
          onClick={() => onSelectTab('opportunities')}
        >
          <span>{opportunity.title}</span>
          <span className="text-muted">{opportunity.target_label ?? 'Catalog'}</span>
        </button>
      ))}
    </>
  );
}

function Kpi({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <Card>
      <CardContent className="grid gap-1">
        <span className="text-muted text-xs">{label}</span>
        <strong className="text-2xl">{value}</strong>
      </CardContent>
    </Card>
  );
}
