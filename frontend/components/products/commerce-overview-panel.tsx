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
      description="Import one company catalog or add its products manually. Competitor alternatives come from audit citations, not catalog rows."
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
  const categoryProducts = (queries.productsQuery.data ?? []).filter(
    (product) => categoryIdentity(product.attributes.category) === categoryIdentity(category),
  );
  const categoryPrompts = prompts.filter((prompt) => prompt.topic_id === topic.id);
  return categoryProducts.every((product) => {
    const namedPrompts = categoryPrompts.filter((prompt) =>
      prompt.text.toLocaleLowerCase().includes(product.name.toLocaleLowerCase()),
    );
    const intents = new Set(namedPrompts.map((prompt) => prompt.intent));
    return intents.has('discovery') && intents.has('comparison');
  });
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
        description="Create one buyer-destination and one alternatives prompt for every catalog product. Each question names the product buyers are researching."
        action={
          <Button
            onClick={() => queries.generatePromptsMutation.mutate({})}
            disabled={
              !queries.setupReady ||
              queries.generatePromptsMutation.isPending ||
              queries.missingCategorySkus.length > 0
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
      <div className="grid gap-4" data-testid="commerce-overview-panel">
        <CommercePrompts queries={queries} />
        <EmptyState
          icon={Play}
          heading="Run your first Commerce visibility audit"
          description="Review the product-named buyer prompts, then launch the citation-capable Commerce audit."
          action={<Button onClick={onLaunchAudit}>Launch Commerce audit</Button>}
        />
      </div>
    );
  }
  const visibility = queries.visibilityQuery.data;
  const summary = visibility.summary;
  const competitorMentions = visibility.citation_comparison.categories
    .flatMap((category) => category.competitor_mentions)
    .reduce((counts, competitor) => {
      counts.set(
        competitor.competitor_name,
        (counts.get(competitor.competitor_name) ?? 0) + competitor.response_count,
      );
      return counts;
    }, new Map<string, number>());
  const competitors = [...competitorMentions].sort(
    ([leftName, leftCount], [rightName, rightCount]) =>
      rightCount - leftCount || leftName.localeCompare(rightName),
  );

  return (
    <div className="grid gap-5" data-testid="commerce-overview-panel">
      <CommercePrompts queries={queries} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi
          label="Products visible"
          value={`${summary.products_visible}/${summary.products_tracked}`}
        />
        <Kpi label="Visibility rate" value={formatPercent(summary.visibility_rate)} />
        <Kpi label="Competitors mentioned" value={String(competitors.length)} />
        <Kpi label="Average rank" value={formatAvgRank(summary.average_rank)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Competitor presence</CardTitle>
            <CardDescription>
              Brands surfaced beside your catalog in the latest audit.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm">
            <div className="grid grid-cols-2 gap-3">
              <div className="border-border-subtle bg-well/30 rounded-md border p-3">
                <span className="text-muted block text-xs">Responses analyzed</span>
                <strong className="text-foreground text-lg font-semibold">
                  {visibility.total_analyses}
                </strong>
              </div>
              <div className="border-border-subtle bg-well/30 rounded-md border p-3">
                <span className="text-muted block text-xs">Products observed</span>
                <strong className="text-foreground text-lg font-semibold">
                  {summary.products_visible}
                </strong>
              </div>
            </div>
            <button
              className="text-accent-text hover:text-accent-hover w-fit text-sm font-medium hover:underline"
              type="button"
              onClick={() => onSelectTab('visibility')}
            >
              View AI Visibility →
            </button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Most-mentioned competitors</CardTitle>
            <CardDescription>
              Competitor response presence across catalog categories.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm">
            {competitors.slice(0, 3).map(([name, count]) => (
              <div
                key={name}
                className="border-border-subtle flex items-center justify-between rounded-md border p-2.5"
              >
                <span className="text-foreground font-medium">{name}</span>
                <span className="bg-well text-secondary rounded px-2 py-0.5 text-xs">
                  {count} responses
                </span>
              </div>
            ))}
            {!competitors.length ? (
              <p className="text-muted text-sm">No configured competitors were mentioned.</p>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function CommercePrompts({ queries }: Readonly<{ queries: OverviewQueries }>) {
  const prompts =
    queries.commercePromptSet?.prompts.filter((prompt) => prompt.cohort === 'commerce') ?? [];
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>Commerce Product Visibility prompts</CardTitle>
          <CardDescription>
            Read-only buyer questions generated from persisted product names and categories.
          </CardDescription>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => queries.generatePromptsMutation.mutate({ regenerate: true })}
          disabled={queries.generatePromptsMutation.isPending}
        >
          {queries.generatePromptsMutation.isPending ? 'Regenerating…' : 'Regenerate'}
        </Button>
      </CardHeader>
      <CardContent className="grid gap-4">
        {queries.categories.map((category) => {
          const topic = queries.topicsQuery.data?.find(
            (item) => categoryIdentity(item.name) === categoryIdentity(category),
          );
          const rows = prompts.filter((prompt) => prompt.topic_id === topic?.id);
          return (
            <div
              key={category}
              className="border-border-subtle bg-well/20 grid gap-2.5 rounded-lg border p-3.5"
            >
              <div className="flex items-center justify-between">
                <strong className="text-foreground text-sm font-semibold">{category}</strong>
                <span className="text-muted text-2xs">{rows.length} prompts</span>
              </div>
              <div className="grid gap-1.5">
                {rows.map((prompt) => (
                  <div
                    key={prompt.id}
                    className="border-border-subtle bg-panel flex items-start gap-2 rounded border p-2.5"
                  >
                    <span className="bg-well text-secondary text-2xs inline-block shrink-0 rounded px-1.5 py-0.5 font-medium uppercase">
                      {prompt.intent || 'discovery'}
                    </span>
                    <p className="text-foreground text-xs leading-relaxed">{prompt.text}</p>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
        {queries.generatePromptsMutation.isError ? (
          <Alert tone="danger">
            {queries.generatePromptsMutation.error instanceof Error
              ? queries.generatePromptsMutation.error.message
              : 'Prompt regeneration failed.'}
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Kpi({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <Card>
      <CardContent className="grid gap-1 p-4">
        <span className="text-muted text-xs">{label}</span>
        <strong className="text-foreground text-2xl font-semibold tracking-tight">{value}</strong>
      </CardContent>
    </Card>
  );
}
