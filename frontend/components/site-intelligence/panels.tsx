'use client';

import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { CoverageBadge, Ratio, ScoreWithCoverage } from '@/components/site-intelligence/coverage';
import { siteIntelligenceQueries } from '@/lib/api/site-intelligence';
import type { IntelligenceOverview } from '@/lib/api/types';

type PanelProps = Readonly<{
  projectId: string;
  crawlId?: string;
  overview: IntelligenceOverview;
}>;

/**
 * A section that has nothing to show, and says WHY.
 *
 * "No data" is not an acceptable answer here: a user must be able to tell an
 * unfinished crawl from a site that published nothing from an analyzer that
 * cannot read this yet.
 */
function NothingToShow({ reason }: Readonly<{ reason: string }>) {
  return <p className="text-muted p-[var(--card-padding)] text-sm">{reason}</p>;
}

/**
 * The body of a card driven by one query, with its three states kept apart.
 *
 * Pending and failed must never render the empty-result copy. "No entities were
 * established from this crawl's evidence" is a FINDING about the site; showing
 * it while the request is still in flight, or after it failed, states that
 * finding on no evidence at all.
 */
function QueryBody({
  query,
  empty,
  children,
}: Readonly<{
  query: { isPending: boolean; isError: boolean };
  empty: string;
  children: ReactNode;
}>) {
  if (query.isPending) {
    return <NothingToShow reason="Loading…" />;
  }
  if (query.isError) {
    return <NothingToShow reason="Could not load this section. Please refresh." />;
  }
  return children ?? <NothingToShow reason={empty} />;
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------
export function OverviewPanel({ overview }: PanelProps) {
  const { dimensions, coverage, knowledge, corpus } = overview;
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Site Intelligence</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <ScoreWithCoverage
            label="Composite"
            score={dimensions.composite_score}
            coverage={dimensions.composite_coverage}
          />
          <div className="grid gap-0.5">
            <span className="text-muted text-2xs tracking-wide uppercase">Questions answered</span>
            <span className="text-heading-sm text-foreground tabular-nums">
              <Ratio value={coverage.answered_ratio} unavailableLabel="—" />
            </span>
            <span className="text-muted text-2xs">of {coverage.denominator} the pack requires</span>
          </div>
          <div className="grid gap-0.5">
            <span className="text-muted text-2xs tracking-wide uppercase">Knowledge</span>
            <span className="text-heading-sm text-foreground tabular-nums">
              {knowledge.entity_count}
            </span>
            <span className="text-muted text-2xs">
              entities · {knowledge.assertion_count} facts · {knowledge.relation_count} links
            </span>
          </div>
          <div className="grid gap-0.5">
            <span className="text-muted text-2xs tracking-wide uppercase">Corpus</span>
            <span className="text-heading-sm text-foreground tabular-nums">
              {corpus.discovered}
            </span>
            <span className="text-muted text-2xs">
              {corpus.analyzable} analyzed · {corpus.documents} documents
            </span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Dimensions</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          {dimensions.dimensions.map((dimension) => {
            const unavailable = dimension.components.filter((c) => c.score === null);
            return (
              <div key={dimension.dimension_id} className="grid gap-1">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-foreground text-sm">{dimension.label}</span>
                  <span className="text-muted text-2xs">
                    <Ratio value={dimension.score} /> ·{' '}
                    <Ratio value={dimension.coverage} unavailableLabel="?" /> observable
                  </span>
                </div>
                {/* The bar shows the score over the FULL denominator; the
                    unavailable note beside it is what explains the gap. */}
                <div
                  className="bg-neutral-bg h-1 w-full overflow-hidden rounded-sm"
                  role="presentation"
                >
                  <div
                    className="bg-accent h-full"
                    style={{ width: `${Math.round(dimension.score * 100)}%` }}
                  />
                </div>
                {unavailable.length > 0 ? (
                  <p className="text-muted text-2xs">
                    Not measurable: {unavailable.map((c) => c.label).join(', ')}
                  </p>
                ) : null}
              </div>
            );
          })}
        </CardContent>
      </Card>

      {knowledge.warnings.length > 0 ? (
        <Alert tone="info">
          Extraction notes: {knowledge.warnings.join('; ').replaceAll('_', ' ')}
        </Alert>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Knowledge
// ---------------------------------------------------------------------------
/**
 * A count in a card title, only once it is known.
 *
 * `?? 0` on a pending query renders "Entities (0)" — a claim the crawl found
 * nothing, made before the answer arrived.
 */
function countLabel(query: Readonly<{ data?: { total: number } }>): string {
  return query.data ? ` (${query.data.total})` : '';
}

export function KnowledgePanel({ projectId, crawlId }: PanelProps) {
  const entities = useQuery(siteIntelligenceQueries.entities(projectId, crawlId));
  const assertions = useQuery(siteIntelligenceQueries.assertions(projectId, crawlId));
  const contradictions = useQuery(siteIntelligenceQueries.contradictions(projectId, crawlId));

  return (
    <div className="grid gap-4">
      {/* A failed contradictions request must SAY so. This card is absent when
          nothing conflicts, so letting an error render the same absence states
          "no facts conflict" — the strongest claim in this panel — on no
          evidence at all. */}
      {contradictions.isError ? (
        <Alert tone="danger">
          Conflicting facts could not be loaded. This is not a finding that the crawl&apos;s facts
          agree.
        </Alert>
      ) : null}
      {(contradictions.data?.items.length ?? 0) > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Conflicting facts</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            {/* Every side is shown and none is pre-selected: the whole point of
                preserving them is that nothing silently chose a winner. */}
            {contradictions.data?.items.map((group) => (
              <div key={group.contradiction_group_id} className="grid gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-foreground text-sm">{group.subject.canonical_name}</span>
                  <code className="text-muted text-2xs">{group.predicate_id}</code>
                  <Badge variant="status" value="danger">
                    {group.sides.length} conflicting values
                  </Badge>
                </div>
                <ul className="text-muted grid gap-0.5 text-sm">
                  {group.sides.map((side) => (
                    <li key={side.id} className="flex flex-wrap gap-2">
                      <span className="text-foreground">{side.normalized_value}</span>
                      <span className="text-2xs">
                        {side.temporal_state} · {side.evidence_refs.length} source(s)
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Entities{countLabel(entities)}</CardTitle>
        </CardHeader>
        <QueryBody
          query={entities}
          empty="No entities were established from this crawl's evidence."
        >
          {entities.data?.items.length ? (
            <CardContent className="grid gap-2">
              {entities.data.items.map((entity) => (
                <div key={entity.id} className="flex flex-wrap items-baseline gap-2">
                  <span className="text-foreground text-sm">{entity.canonical_name || '—'}</span>
                  <code className="text-muted text-2xs">{entity.entity_type_id}</code>
                  <span className="text-muted text-2xs">
                    evidenced on {entity.evidence_page_count} page(s)
                  </span>
                </div>
              ))}
            </CardContent>
          ) : null}
        </QueryBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Facts{countLabel(assertions)}</CardTitle>
        </CardHeader>
        <QueryBody query={assertions} empty="No facts could be evidenced from this crawl's pages.">
          {assertions.data?.items.length ? (
            <CardContent className="grid gap-2">
              {assertions.data.items.map((assertion) => (
                <div key={assertion.id} className="flex flex-wrap items-baseline gap-2">
                  <code className="text-muted text-2xs">{assertion.predicate_id}</code>
                  <span className="text-foreground text-sm">{assertion.normalized_value}</span>
                  <Badge>{assertion.temporal_state}</Badge>
                  {/* An unscoped claim is missing a qualifier the pack requires
                      — a fee with no stated year or grade. Rendering it exactly
                      like a fully qualified one publishes it as if scoped. */}
                  {assertion.scope_complete ? null : (
                    <Badge variant="status" value="warning">
                      unscoped
                    </Badge>
                  )}
                  {assertion.contradiction_group_id ? (
                    <Badge variant="status" value="danger">
                      conflicting
                    </Badge>
                  ) : null}
                </div>
              ))}
            </CardContent>
          ) : null}
        </QueryBody>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------
export function SchemaPanel({ projectId, crawlId }: PanelProps) {
  const graph = useQuery(siteIntelligenceQueries.schemaGraph(projectId, crawlId));
  const data = graph.data;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Structured data</CardTitle>
      </CardHeader>
      {graph.isError ? (
        <NothingToShow reason="Could not load the schema graph. Please refresh." />
      ) : data ? (
        <CardContent className="grid gap-4">
          <p className="text-muted text-sm">
            {data.pages_with_schema} of {data.analyzed_pages} analyzed pages publish structured
            data.
          </p>
          {data.types.length ? (
            <div className="grid gap-1">
              {data.types.map((entry) => (
                <div key={entry.type} className="flex flex-wrap items-baseline gap-2">
                  <span className="text-foreground text-sm">{entry.type}</span>
                  <span className="text-muted text-2xs">{entry.pages} page(s)</span>
                  {entry.invalid > 0 ? (
                    <Badge variant="status" value="warning">
                      {entry.invalid} incomplete
                    </Badge>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-muted text-sm">
              No recognized structured data. Role classification does not depend on it — every
              signal is also read from visible content — but machine clarity scores zero for it.
            </p>
          )}
        </CardContent>
      ) : (
        <NothingToShow reason="Loading the schema graph…" />
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Journeys
// ---------------------------------------------------------------------------
export function JourneysPanel({ overview }: PanelProps) {
  if (overview.journeys.length === 0) {
    return (
      <Card>
        <NothingToShow reason="This crawl's pack declares no journey." />
      </Card>
    );
  }
  return (
    <div className="grid gap-4">
      {overview.journeys.map((journey) => (
        <Card key={journey.journey_id}>
          <CardHeader>
            <CardTitle>{journey.label}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            {journey.stages.map((stage) => (
              <div key={stage.stage_id} className="grid gap-1">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-foreground text-sm">{stage.label}</span>
                  <span className="text-muted text-2xs">
                    pages <Ratio value={stage.role_coverage} /> · answers{' '}
                    <Ratio value={stage.question_coverage} unavailableLabel="n/a" />
                  </span>
                </div>
                {stage.missing_role_ids.length > 0 ? (
                  <p className="text-muted text-2xs">
                    No page for: {stage.missing_role_ids.join(', ')}
                  </p>
                ) : null}
                {/* Outcomes are `unavailable`, never zero: no conversions and no
                    way to measure conversions are opposite findings. The count
                    is derived rather than asserted, so this copy stays true once
                    events start arriving. */}
                <StageOutcomes outcomes={stage.outcomes} />
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function StageOutcomes({ outcomes }: Readonly<{ outcomes: Record<string, string> }>) {
  const values = Object.values(outcomes);
  const unavailable = values.filter((state) => state === 'unavailable').length;
  return (
    <p className="text-muted text-2xs">
      Outcomes: {values.length} defined
      {unavailable > 0
        ? `, ${unavailable} not measurable until analytics events are connected`
        : ''}
      .
    </p>
  );
}

// ---------------------------------------------------------------------------
// Evidence
// ---------------------------------------------------------------------------
export function EvidencePanel({ projectId, crawlId, overview }: PanelProps) {
  const relations = useQuery(siteIntelligenceQueries.relations(projectId, crawlId));

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Question coverage</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2">
          {overview.coverage.questions.map((question) => (
            <div key={question.question_id} className="flex flex-wrap items-baseline gap-2">
              <CoverageBadge state={question.state} />
              <span className="text-foreground text-sm">{question.label}</span>
              {/* Each state carries its own reason; a state with no explanation
                  is not actionable. */}
              <span className="text-muted text-2xs">{question.reason}</span>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Relationships{countLabel(relations)}</CardTitle>
        </CardHeader>
        <QueryBody
          query={relations}
          empty="No relationships were evidenced between this crawl's entities."
        >
          {relations.data?.items.length ? (
            <CardContent className="grid gap-1">
              {relations.data.items.map((relation) => (
                <div key={relation.id} className="flex flex-wrap items-baseline gap-2 text-sm">
                  <span className="text-foreground">{relation.source.name || '—'}</span>
                  <code className="text-muted text-2xs">{relation.relation_type_id}</code>
                  <span className="text-foreground">{relation.target.name || '—'}</span>
                </div>
              ))}
            </CardContent>
          ) : null}
        </QueryBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Provenance</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-1 text-sm">
          {/* The FROZEN manifest this crawl was analyzed under — not whatever
              the catalog says today. */}
          {Object.entries(overview.manifest ?? {}).map(([key, value]) => (
            <div key={key} className="flex flex-wrap gap-2">
              <span className="text-muted text-2xs">{key.replaceAll('_', ' ')}</span>
              <code className="text-foreground text-2xs">{value}</code>
            </div>
          ))}
          {Object.entries(overview.versions).map(([key, value]) => (
            <div key={key} className="flex flex-wrap gap-2">
              <span className="text-muted text-2xs">{key.replaceAll('_', ' ')}</span>
              <code className="text-foreground text-2xs">{value}</code>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
