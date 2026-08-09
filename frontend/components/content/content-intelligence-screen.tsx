'use client';

import { BookOpenCheck, FileCheck2, Files, ListChecks, RefreshCw, SearchCheck } from 'lucide-react';
import Link from 'next/link';
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { ContentScreen } from '@/components/content/content-screen';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Input, Textarea } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import type { ContentSkill } from '@/lib/api/content';
import { siteIntelligenceQueries } from '@/lib/api/site-intelligence';
import type { ContentBrief, ContentRevision } from '@/lib/api/types';
import { useContentIntelligence } from '@/lib/content/use-content-intelligence';
import { useActiveProject } from '@/lib/project/project-context';
import { saveBlob } from '@/lib/site-health/download';

export type ContentPanel =
  'strategy' | 'inventory' | 'briefs' | 'drafts' | 'revisions' | 'verification';

const BRIEF_SKILLS: ReadonlyArray<{
  skillId: ContentSkill;
  label: string;
  kinds: readonly string[];
}> = [
  { skillId: 'faq_visible', label: 'Generate FAQ', kinds: ['faq'] },
  { skillId: 'faq_jsonld', label: 'Generate FAQ schema', kinds: ['faq_schema'] },
  { skillId: 'answer_first', label: 'Generate answer-first draft', kinds: ['section', 'new_page'] },
  {
    skillId: 'page_refresh',
    label: 'Generate page refresh',
    kinds: ['page_refresh', 'consolidation'],
  },
  { skillId: 'comparison', label: 'Generate comparison', kinds: ['comparison'] },
  { skillId: 'guide', label: 'Generate guide', kinds: ['guide'] },
  { skillId: 'commerce_category', label: 'Generate category copy', kinds: ['category'] },
  { skillId: 'commerce_pdp', label: 'Generate product copy', kinds: ['pdp'] },
  { skillId: 'commerce_policy', label: 'Generate policy copy', kinds: ['policy'] },
  { skillId: 'internal_links', label: 'Generate link plan', kinds: ['internal_links'] },
];

function skillForBrief(brief: ContentBrief) {
  return BRIEF_SKILLS.find((candidate) => candidate.kinds.includes(brief.kind));
}

function text(value: unknown, fallback = 'Unavailable'): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function count(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function LoadingPanel() {
  return (
    <div className="grid gap-3" aria-label="Loading Content Intelligence">
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

export function ContentIntelligenceScreen({
  panel,
  opportunityId,
  revisionId,
}: Readonly<{
  panel: ContentPanel;
  opportunityId?: string | null;
  revisionId?: string | null;
}>) {
  const project = useActiveProject();
  if (!project) {
    return (
      <EmptyState
        icon={Files}
        heading="Choose a project"
        description="Content Intelligence needs a project and its persisted site evidence."
        action={
          <Button asChild>
            <Link href="/projects">Open projects</Link>
          </Button>
        }
      />
    );
  }
  if (panel === 'drafts') return <ContentScreen opportunityId={opportunityId} />;
  return (
    <ProjectContentIntelligence
      key={project.id}
      projectId={project.id}
      panel={panel}
      revisionId={revisionId}
    />
  );
}

function ProjectContentIntelligence({
  projectId,
  panel,
  revisionId,
}: Readonly<{ projectId: string; panel: ContentPanel; revisionId?: string | null }>) {
  const content = useContentIntelligence(projectId);
  let surface;
  if (panel === 'strategy') surface = <StrategyPanel content={content} />;
  else if (panel === 'inventory') surface = <InventoryPanel content={content} />;
  else if (panel === 'briefs') surface = <BriefsPanel content={content} />;
  else if (panel === 'revisions')
    surface = <RevisionsPanel content={content} revisionId={revisionId} />;
  else surface = <VerificationPanel content={content} projectId={projectId} />;
  const mutationFailed = [
    content.recomputeMutation,
    content.createBriefMutation,
    content.generateBriefMutation,
    content.createRevisionMutation,
    content.updateRevisionMutation,
    content.transitionRevisionMutation,
    content.verifyRevisionMutation,
    content.exportRevisionMutation,
  ].some((mutation) => mutation.isError);
  return (
    <div className="grid gap-4">
      {mutationFailed ? (
        <Alert tone="danger">
          The content action could not be completed. Review the evidence or validation state and try
          again.
        </Alert>
      ) : null}
      {surface}
    </div>
  );
}

type ContentHook = ReturnType<typeof useContentIntelligence>;

function StrategyPanel({ content }: Readonly<{ content: ContentHook }>) {
  const strategy = content.strategyQuery.data;
  if (content.strategyQuery.isLoading) return <LoadingPanel />;
  if (!strategy) {
    return (
      <EmptyState
        icon={ListChecks}
        heading="Build the first content strategy"
        description="Freeze the latest Site Intelligence evidence into an inventory and ranked program."
        action={
          <Button
            disabled={content.recomputeMutation.isPending}
            onClick={() => content.recomputeMutation.mutate()}
          >
            Build strategy
          </Button>
        }
      />
    );
  }
  const total = count(strategy.inventory_summary.total);
  const questions = Array.isArray(strategy.coverage.questions) ? strategy.coverage.questions : [];
  const missing = questions.filter((item) => {
    const record = item as Record<string, unknown>;
    return record.state === 'missing';
  }).length;

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-[70ch]">
          <h2 className="font-display text-2xl">Evidence into a sequenced content program</h2>
          <p className="text-secondary mt-2 text-sm leading-relaxed">
            Deterministic priorities from the latest compatible Site snapshot and available Demand
            evidence. Recomputing creates a new immutable strategy when its sources change.
          </p>
        </div>
        <Button
          variant="secondary"
          disabled={content.recomputeMutation.isPending}
          onClick={() => content.recomputeMutation.mutate()}
        >
          <RefreshCw className="mr-2 size-4" aria-hidden />
          Recompute
        </Button>
      </div>
      <dl className="bg-border grid gap-px overflow-hidden rounded-lg sm:grid-cols-3">
        <Metric label="Inventory" value={total} detail="persisted pages and documents" />
        <Metric
          label="Required questions"
          value={questions.length}
          detail="full pack denominator"
        />
        <Metric label="Missing answers" value={missing} detail="eligible for an FAQ brief" />
      </dl>
      <section aria-labelledby="content-priorities-title" className="grid gap-3">
        <div>
          <h3 id="content-priorities-title" className="text-lg">
            Ranked priorities
          </h3>
          <p className="text-secondary mt-1 text-sm">
            Each row keeps its question state and deterministic score visible.
          </p>
        </div>
        <div className="shadow-card overflow-hidden rounded-lg">
          {(strategy.priorities ?? []).length === 0 ? (
            <p className="bg-panel text-secondary p-5 text-sm">No actionable question gaps.</p>
          ) : (
            <ol className="divide-border bg-panel divide-y">
              {strategy.priorities.map((priority, index) => (
                <li
                  key={`${text(priority.question_id)}-${index}`}
                  className="grid gap-2 p-4 sm:grid-cols-[1fr_auto] sm:items-center"
                >
                  <div>
                    <p className="text-foreground text-sm font-medium">
                      {text(priority.question_id, 'Unnamed question')}
                    </p>
                    <p className="text-secondary mt-1 text-sm">{text(priority.reason)}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge>{text(priority.state)}</Badge>
                    <span className="text-muted text-xs tabular-nums">
                      Priority {count(priority.score)}
                    </span>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      </section>
      {strategy.limitations.length ? (
        <Alert tone="info">Limitations: {strategy.limitations.map(String).join(', ')}</Alert>
      ) : null}
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
}: Readonly<{ label: string; value: number; detail: string }>) {
  return (
    <div className="bg-panel p-4">
      <dt className="text-secondary text-xs font-medium">{label}</dt>
      <dd className="text-foreground font-display mt-2 text-2xl tabular-nums">{value}</dd>
      <dd className="text-muted mt-1 text-xs">{detail}</dd>
    </div>
  );
}

function InventoryPanel({ content }: Readonly<{ content: ContentHook }>) {
  if (content.inventoryQuery.isLoading) return <LoadingPanel />;
  const items = content.inventoryQuery.data ?? [];
  if (!items.length) {
    return (
      <EmptyState
        icon={Files}
        heading="No content inventory yet"
        description="Build a strategy to project the latest Site Intelligence corpus into content units."
      />
    );
  }
  return (
    <section className="grid gap-4" aria-labelledby="inventory-title">
      <div>
        <h2 id="inventory-title" className="font-display text-2xl">
          Content inventory
        </h2>
        <p className="text-secondary mt-2 text-sm">
          {items.length} persisted units from one Site snapshot.
        </p>
      </div>
      <div className="shadow-card overflow-hidden rounded-lg">
        <div className="bg-background-alt text-secondary hidden grid-cols-[minmax(18rem,2fr)_1fr_1fr_auto] gap-4 px-4 py-2 text-xs font-medium md:grid">
          <span>Page</span>
          <span>Role</span>
          <span>Kind</span>
          <span>State</span>
        </div>
        <ul className="divide-border bg-panel divide-y">
          {items.map((item) => (
            <li
              key={item.id}
              className="grid gap-3 p-4 md:grid-cols-[minmax(18rem,2fr)_1fr_1fr_auto] md:items-center"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">
                  {text(item.purpose.title, item.canonical_url)}
                </p>
                <p className="text-muted mt-1 truncate text-xs">{item.canonical_url}</p>
              </div>
              <LabeledValue label="Role" value={item.industry_role_id ?? 'Unclassified'} />
              <LabeledValue label="Kind" value={item.page_kind} />
              <Badge>{item.temporal_state}</Badge>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function LabeledValue({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="text-sm">
      <span className="text-muted mr-2 text-xs md:hidden">{label}</span>
      <span className="text-secondary">{value}</span>
    </div>
  );
}

function BriefsPanel({ content }: Readonly<{ content: ContentHook }>) {
  const strategy = content.strategyQuery.data;
  const briefs = content.briefsQuery.data ?? [];
  const missing = useMemo(() => {
    const priorities = strategy?.priorities ?? [];
    return priorities.filter((item) => item.state === 'missing');
  }, [strategy]);
  if (content.briefsQuery.isLoading || content.strategyQuery.isLoading) return <LoadingPanel />;
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.55fr)]">
      <section className="grid content-start gap-3" aria-labelledby="briefs-title">
        <div>
          <h2 id="briefs-title" className="font-display text-2xl">
            Frozen briefs
          </h2>
          <p className="text-secondary mt-2 text-sm">
            Requirements and evidence are immutable; changed sources create a new version.
          </p>
        </div>
        {briefs.length === 0 ? (
          <EmptyState
            icon={BookOpenCheck}
            heading="No briefs yet"
            description="Create one from a missing required-question gap."
          />
        ) : (
          <ul className="divide-border bg-panel shadow-card divide-y overflow-hidden rounded-lg">
            {briefs.map((brief) => (
              <li key={brief.id} className="grid gap-3 p-4 sm:grid-cols-[1fr_auto] sm:items-center">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium">{brief.title}</p>
                    <Badge>v{brief.version}</Badge>
                  </div>
                  <p className="text-secondary mt-2 text-xs">
                    {brief.allowed_facts.length} allowed facts · {brief.prohibited_claims.length}{' '}
                    blocked claims · {brief.source_refs.length} sources
                  </p>
                </div>
                <BriefGenerationButton brief={brief} content={content} />
              </li>
            ))}
          </ul>
        )}
      </section>
      <aside className="grid content-start gap-3" aria-labelledby="brief-ready-title">
        <h3 id="brief-ready-title" className="text-lg">
          Ready gaps
        </h3>
        {missing.length === 0 ? (
          <p className="text-secondary text-sm">No automatically briefable missing questions.</p>
        ) : (
          <ul className="divide-border bg-panel shadow-card divide-y overflow-hidden rounded-lg">
            {missing.slice(0, 12).map((priority, index) => (
              <li key={`${text(priority.question_id)}-${index}`} className="grid gap-3 p-4">
                <p className="text-sm font-medium">{text(priority.question_id)}</p>
                <Button
                  variant="secondary"
                  disabled={content.createBriefMutation.isPending}
                  onClick={() =>
                    content.createBriefMutation.mutate({
                      questionId: text(priority.question_id),
                      targetUrl: '',
                    })
                  }
                >
                  Create brief
                </Button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}

function BriefGenerationButton({
  brief,
  content,
}: Readonly<{ brief: ContentBrief; content: ContentHook }>) {
  const skill = skillForBrief(brief);
  return (
    <Button
      disabled={!skill || content.generateBriefMutation.isPending}
      onClick={() =>
        skill &&
        content.generateBriefMutation.mutate({
          briefId: brief.id,
          skillId: skill.skillId,
        })
      }
    >
      {skill?.label ?? 'Unsupported brief kind'}
    </Button>
  );
}

function RevisionsPanel({
  content,
  revisionId,
}: Readonly<{ content: ContentHook; revisionId?: string | null }>) {
  if (content.revisionsQuery.isLoading) return <LoadingPanel />;
  const revisions = content.revisionsQuery.data ?? [];
  if (!revisions.length) {
    return (
      <EmptyState
        icon={FileCheck2}
        heading="No revisions yet"
        description="Open a validated draft and start a revision before saving."
      />
    );
  }
  return <RevisionEditor revisions={revisions} content={content} revisionId={revisionId} />;
}

function RevisionEditor({
  revisions,
  content,
  revisionId,
}: Readonly<{
  revisions: ContentRevision[];
  content: ContentHook;
  revisionId?: string | null;
}>) {
  const initialId = revisions.some((item) => item.id === revisionId)
    ? (revisionId ?? revisions[0].id)
    : revisions[0].id;
  const [selectedId, setSelectedId] = useState(initialId);
  const selected = revisions.find((item) => item.id === selectedId) ?? revisions[0];
  const [body, setBody] = useState(selected.visible_content);
  const [targetUrl, setTargetUrl] = useState(selected.publication_target_url);
  const selectRevision = (revision: ContentRevision) => {
    setSelectedId(revision.id);
    setBody(revision.visible_content);
    setTargetUrl(revision.publication_target_url);
  };
  const editable = selected.state === 'draft' || selected.state === 'edited';
  return (
    <div className="grid gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <nav
        aria-label="Content revisions"
        className="bg-panel shadow-card overflow-hidden rounded-lg"
      >
        {revisions.map((revision) => (
          <button
            key={revision.id}
            type="button"
            onClick={() => selectRevision(revision)}
            aria-current={revision.id === selected.id ? 'page' : undefined}
            className="focus-ring border-border hover:bg-background-alt flex min-h-11 w-full items-center justify-between gap-2 border-b px-3 text-left text-sm last:border-b-0"
          >
            <span className="truncate">
              {revision.visible_content.split('\n')[0] || 'Untitled revision'}
            </span>
            <Badge>{revision.state}</Badge>
          </button>
        ))}
      </nav>
      <Card>
        <CardHeader>
          <CardTitle>Edit, save, and record publication</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <label className="grid gap-2 text-sm font-medium">
            Visible content
            <Textarea
              rows={18}
              value={body}
              disabled={!editable}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          {selected.state === 'saved' ? (
            <label className="grid gap-2 text-sm font-medium">
              Publication URL
              <Input
                value={targetUrl}
                onChange={(event) => setTargetUrl(event.target.value)}
                placeholder="https://example.com/faq"
              />
            </label>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Badge>{text(selected.validation_snapshot.status, 'not validated')}</Badge>
            {editable ? (
              <>
                <Button
                  variant="secondary"
                  disabled={content.updateRevisionMutation.isPending || !body.trim()}
                  onClick={() =>
                    content.updateRevisionMutation.mutate({
                      revisionId: selected.id,
                      visibleContent: body,
                    })
                  }
                >
                  Save edit
                </Button>
                <Button
                  disabled={
                    content.transitionRevisionMutation.isPending ||
                    selected.validation_snapshot.status !== 'passed'
                  }
                  onClick={() =>
                    content.transitionRevisionMutation.mutate({
                      revisionId: selected.id,
                      state: 'saved',
                    })
                  }
                >
                  Save revision
                </Button>
              </>
            ) : null}
            {selected.state === 'saved' ? (
              <Button
                disabled={content.transitionRevisionMutation.isPending || !targetUrl.trim()}
                onClick={() =>
                  content.transitionRevisionMutation.mutate({
                    revisionId: selected.id,
                    state: 'published_claimed',
                    targetUrl,
                  })
                }
              >
                Record publication claim
              </Button>
            ) : null}
            <Button
              variant="secondary"
              disabled={content.exportRevisionMutation.isPending}
              onClick={async () => {
                const blob = await content.exportRevisionMutation.mutateAsync(selected.id);
                saveBlob(blob, `content-revision-${selected.id.slice(0, 8)}.md`);
              }}
            >
              Export Markdown
            </Button>
          </div>
          <p className="text-muted text-xs">
            Saving this revision does not make any sentence a project fact.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function VerificationPanel({
  content,
  projectId,
}: Readonly<{ content: ContentHook; projectId: string }>) {
  const overviewQuery = useQuery(siteIntelligenceQueries.overview(projectId));
  if (
    content.verificationsQuery.isLoading ||
    content.revisionsQuery.isLoading ||
    overviewQuery.isLoading
  )
    return <LoadingPanel />;
  const strategy = content.strategyQuery.data;
  const latestSiteSnapshotId = overviewQuery.data?.snapshot_id;
  const claims = (content.revisionsQuery.data ?? []).filter(
    (item) => item.state === 'published_claimed',
  );
  const verifications = content.verificationsQuery.data ?? [];
  return (
    <div className="grid gap-6">
      <div>
        <h2 className="font-display text-2xl">Observed after publication</h2>
        <p className="text-secondary mt-2 max-w-[70ch] text-sm">
          Verification compares saved requirements with later persisted Site evidence. Demand
          associations are descriptive, never causal.
        </p>
      </div>
      {claims.length ? (
        <section className="grid gap-3" aria-labelledby="claims-title">
          <h3 id="claims-title" className="text-lg">
            Publication claims awaiting observation
          </h3>
          <ul className="divide-border bg-panel shadow-card divide-y overflow-hidden rounded-lg">
            {claims.map((revision) => (
              <li
                key={revision.id}
                className="flex flex-wrap items-center justify-between gap-3 p-4"
              >
                <div>
                  <p className="text-sm font-medium">{revision.publication_target_url}</p>
                  <p className="text-muted mt-1 text-xs">
                    Claimed {revision.publication_claimed_at ?? 'time unavailable'}
                  </p>
                </div>
                <Button
                  variant="secondary"
                  disabled={!strategy || content.verifyRevisionMutation.isPending}
                  onClick={() =>
                    strategy &&
                    content.verifyRevisionMutation.mutate({
                      revisionId: revision.id,
                      siteSnapshotId: latestSiteSnapshotId ?? strategy.site_snapshot_id,
                    })
                  }
                >
                  <SearchCheck className="mr-2 size-4" aria-hidden />
                  {latestSiteSnapshotId ? 'Compare latest recrawl' : 'Compare strategy snapshot'}
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {verifications.length === 0 ? (
        <EmptyState
          icon={SearchCheck}
          heading="No recrawl verification yet"
          description="Save content, record its publication URL, then compare a later Site snapshot."
        />
      ) : (
        <ul className="divide-border bg-panel shadow-card divide-y overflow-hidden rounded-lg">
          {verifications.map((verification) => (
            <li
              key={verification.id}
              className="grid gap-2 p-4 sm:grid-cols-[1fr_auto] sm:items-center"
            >
              <div>
                <p className="text-sm font-medium">
                  {count(verification.coverage.observed)} of {count(verification.coverage.required)}{' '}
                  requirements observed
                </p>
                <p className="text-muted mt-1 text-xs">
                  Site snapshot {verification.site_snapshot_id}
                </p>
              </div>
              <Badge>{verification.status}</Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
