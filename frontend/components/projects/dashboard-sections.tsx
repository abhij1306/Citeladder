import { ArrowRight, Download, ExternalLink, LoaderCircle } from 'lucide-react';
import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { BrandLogo } from '@/components/ui/brand-logo';
import { Button } from '@/components/ui/button';
import { SectionTitle } from '@/components/ui/typography';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import type { CommandCenter, Project } from '@/lib/api/types';
import { formatUtcTimestamp } from '@/lib/format';
import { cn } from '@/lib/utils';

import { FactsDrawer, ProjectControls } from './dashboard-controls';
import {
  ActionRow,
  deltaLabel,
  metricValue,
  MovementChart,
  StateMetric,
} from './dashboard-primitives';

export function DashboardHeader({
  data,
  projects,
  activeProject,
  activeProjectId,
  setActiveProjectId,
  onEditProject,
  downloading,
  onDownload,
}: Readonly<{
  data: CommandCenter;
  projects: Project[];
  activeProject: Project;
  activeProjectId?: string | null;
  setActiveProjectId: (id: string) => void;
  onEditProject?: (project: Project) => void;
  downloading: boolean;
  onDownload: () => void;
}>) {
  const website = data.project.website_url;
  const facts = data.facts;
  return (
    <section className="bg-panel shadow-card border-border overflow-hidden rounded-[var(--radius-card)] border">
      <div className="flex flex-wrap items-center justify-between gap-4 p-[var(--card-padding)]">
        <div className="flex min-w-0 items-center gap-4">
          <BrandLogo
            name={data.project.brand_name || data.project.name}
            logoUrl={activeProject.brand.logo_url}
            websiteUrl={website}
            size="xl"
            className="size-12 rounded-[var(--radius-control)] shadow-xs"
          />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h2 className="font-display text-foreground truncate text-xl font-semibold tracking-[-0.02em]">
                {data.project.brand_name || data.project.name}
              </h2>
              {website ? (
                <a
                  href={/^https?:\/\//i.test(website) ? website : `https://${website}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-muted hover:text-foreground border-border-subtle bg-background inline-flex items-center gap-1 rounded-[var(--radius-control)] border px-2 py-0.5 text-xs font-medium transition-colors"
                >
                  <span className="truncate">
                    {website.replace(/^https?:\/\//i, '').replace(/\/$/, '')}
                  </span>
                  <ExternalLink className="size-3 shrink-0" aria-hidden />
                </a>
              ) : null}
            </div>
            {data.measurement ? (
              <p className="text-muted mt-1 text-xs">
                Tracked {formatUtcTimestamp(data.measurement.completed_at)} ·{' '}
                {data.measurement.logical_engines.join(', ')}
              </p>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <ProjectControls
            projects={projects}
            activeProject={activeProject}
            activeProjectId={activeProjectId}
            setActiveProjectId={setActiveProjectId}
            onEditProject={onEditProject}
          />
          <FactsDrawer projectId={activeProject.id} competitors={activeProject.competitors ?? []} />
          {data.report_available ? (
            <PdfButton downloading={downloading} onDownload={onDownload} />
          ) : null}
        </div>
      </div>
      <div className="border-border-subtle border-t p-[var(--card-padding)]">
        <div className="mb-3 flex items-center justify-between gap-3">
          <SectionTitle id="company-facts">Company facts</SectionTitle>
          <span className="text-muted text-xs font-medium">
            {facts.industry || 'Industry not set'}
          </span>
        </div>
        <div className="grid gap-3 md:grid-cols-3" aria-labelledby="company-facts">
          <FactSummary
            label="Positioning"
            value={facts.positioning || facts.description}
            emptyState="not_set"
          />
          <FactSummary label="Target audience" value={facts.target_audience} emptyState="not_set" />
          <FactSummary
            label="Offerings & competitors"
            value={facts.products_services.join(', ')}
            emptyState="not_set"
            supporting={`${facts.competitors.length} tracked competitor${facts.competitors.length === 1 ? '' : 's'}`}
          />
        </div>
      </div>
    </section>
  );
}

function FactSummary({
  label,
  value,
  emptyState,
  supporting,
}: Readonly<{
  label: string;
  value: string;
  emptyState: 'not_set';
  supporting?: string;
}>) {
  return (
    <div className="border-border-subtle bg-background min-w-0 rounded-[var(--radius-card)] border p-4">
      <p className={eyebrowClasses}>{label}</p>
      {value.trim() ? (
        <p className="text-foreground mt-1.5 line-clamp-none text-sm leading-snug font-medium md:line-clamp-2">
          {value}
        </p>
      ) : (
        <UnavailableValue state={emptyState} className="mt-1.5 inline-flex" />
      )}
      {supporting ? <p className="text-muted mt-2 text-xs">{supporting}</p> : null}
    </div>
  );
}

function PdfButton({
  downloading,
  onDownload,
}: Readonly<{ downloading: boolean; onDownload: () => void }>) {
  return (
    <Button
      variant="secondary"
      size="sm"
      onClick={onDownload}
      pending={downloading}
      pendingLabel="Preparing…"
      className="gap-1.5"
    >
      {downloading ? (
        <LoaderCircle className="size-4 animate-spin" aria-hidden />
      ) : (
        <Download className="size-4" aria-hidden />
      )}
      {downloading ? 'Preparing…' : 'Executive PDF'}
    </Button>
  );
}

export function SummarySections({ data }: Readonly<{ data: CommandCenter }>) {
  return (
    <>
      <div className="grid gap-[var(--workspace-gap)] lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <NextAction data={data} />
        <Track data={data} />
      </div>
      <section aria-labelledby="project-state" className="grid gap-3">
        <div className="flex items-center justify-between gap-3">
          <SectionTitle id="project-state">Project state</SectionTitle>
          <Badge>{data.measurement ? 'Citation-capable audit' : 'Not run'}</Badge>
        </div>
        <div className="bg-panel shadow-card border-border divide-border-subtle grid divide-y overflow-hidden rounded-[var(--radius-card)] border sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          <StateMetric label="Visibility" {...data.state.visibility} />
          <StateMetric label="Share of voice" {...data.state.share_of_voice} suffix="%" />
          <StateMetric label="Brand rank" {...data.state.brand_rank} inverse />
        </div>
      </section>
      <Movement data={data} />
    </>
  );
}

function NextAction({ data }: Readonly<{ data: CommandCenter }>) {
  return (
    <div className="bg-panel-tonal text-foreground border-border shadow-card flex flex-col justify-between gap-4 rounded-[var(--radius-card)] border p-[var(--card-padding)]">
      <div>
        <div className="flex items-center justify-between">
          <span className="text-accent-text bg-accent-soft inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-sans text-xs font-semibold">
            <span className="bg-accent size-1.5 rounded-full" aria-hidden />
            Next action
          </span>
          <span className="text-muted text-xs font-semibold">
            {data.next_action.kind === 'monitor' ? 'Optimal state' : 'Action recommended'}
          </span>
        </div>
        <p className="font-display text-foreground mt-3 text-lg leading-snug font-semibold">
          {data.next_action.title}
        </p>
        <p className="text-muted mt-1 text-xs leading-relaxed">
          Prioritized from deterministic evidence and current visibility coverage.
        </p>
      </div>
      <Button asChild variant="primary" size="md" className="self-start">
        <Link href={data.next_action.href}>
          {data.next_action.kind === 'monitor' ? 'View trends' : 'Continue'}
          <ArrowRight className="size-4" aria-hidden />
        </Link>
      </Button>
    </div>
  );
}

function Track({ data }: Readonly<{ data: CommandCenter }>) {
  const delta = data.track.citation_share.delta;
  return (
    <section
      aria-labelledby="citation-share-track"
      className="bg-panel shadow-card border-border flex flex-col justify-between gap-4 rounded-[var(--radius-card)] border p-[var(--card-padding)]"
    >
      <div>
        <div className="flex items-center justify-between">
          <span className={eyebrowClasses}>AI Visibility Track</span>
          <span className="text-muted text-xs font-medium">
            {data.track.observed_at ? `${data.track.engine_coverage} engine(s)` : 'No run'}
          </span>
        </div>
        <div className="mt-3">
          <SectionTitle id="citation-share-track">Citation share</SectionTitle>
          <div className="mt-1 flex items-baseline gap-3">
            {data.track.citation_share.value === null ? (
              <UnavailableValue state={data.track.observed_at ? 'unavailable' : 'not_run'} />
            ) : (
              <p className="font-display text-foreground text-3xl leading-none font-semibold tracking-[-0.03em] tabular-nums">
                {metricValue(data.track.citation_share.value, '%')}
              </p>
            )}
            {delta !== null ? (
              <span
                className={cn(
                  'font-display text-xs font-semibold tabular-nums',
                  delta >= 0 ? 'text-success' : 'text-danger',
                )}
              >
                {delta > 0 ? '+' : ''}
                {delta.toFixed(1)}%
              </span>
            ) : null}
          </div>
        </div>
        <p className="text-muted mt-1.5 text-xs leading-relaxed">
          {data.track.observed_at ? deltaLabel(delta) : data.track.limitations[0]}
        </p>
      </div>
      <div className="flex justify-end">
        <Button asChild variant="ghost" size="sm">
          <Link href="/visibility?tab=trends">
            Open Trends <ArrowRight className="ms-1 size-3.5" aria-hidden />
          </Link>
        </Button>
      </div>
    </section>
  );
}

function Movement({ data }: Readonly<{ data: CommandCenter }>) {
  return (
    <div className="bg-panel shadow-card border-border flex flex-col justify-between gap-4 rounded-[var(--radius-card)] border p-[var(--card-padding)]">
      <section aria-labelledby="movement" className="grid gap-3">
        <div>
          <SectionTitle id="movement">Movement</SectionTitle>
          <p className="text-muted mt-0.5 text-xs">
            Only comparable persisted measurements are shown.
          </p>
        </div>
        <MovementChart movements={data.movements} />
      </section>
    </div>
  );
}

export function ActionsAndProof({
  data,
  actions,
  pending,
  onMove,
  downloading,
  onDownload,
}: Readonly<{
  data: CommandCenter;
  actions: CommandCenter['actions'];
  pending: boolean;
  onMove: (from: number, to: number) => void;
  downloading: boolean;
  onDownload: () => void;
}>) {
  return (
    <>
      <div className="bg-panel shadow-card border-border overflow-hidden rounded-[var(--radius-card)] border">
        <section aria-labelledby="ranked-actions">
          <div className="border-border-subtle flex flex-wrap items-center justify-between gap-3 border-b px-[var(--card-padding)] py-4">
            <div>
              <SectionTitle id="ranked-actions">Ranked actions</SectionTitle>
              <p className="text-muted mt-0.5 text-xs">
                Shared order · drag or use the arrow controls.
              </p>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link href="/opportunities">
                View all <ArrowRight className="ms-1 size-3.5" aria-hidden />
              </Link>
            </Button>
          </div>
          {actions.length ? (
            <ol>
              {actions.map((action, index) => (
                <ActionRow
                  key={action.id}
                  action={action}
                  index={index}
                  total={actions.length}
                  onMove={onMove}
                  onDrop={onMove}
                  reorderPending={pending}
                />
              ))}
            </ol>
          ) : (
            <div className="p-[var(--empty-state-padding)] text-center">
              <p className="text-foreground text-sm font-semibold">No open actions</p>
              <p className="text-muted mt-1 text-xs">
                Run another audit to look for new opportunities.
              </p>
            </div>
          )}
        </section>
      </div>
      <div className="bg-panel shadow-card border-border rounded-[var(--radius-card)] border p-[var(--card-padding)]">
        <section
          aria-labelledby="progress-proof"
          className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center"
        >
          <div>
            <SectionTitle id="progress-proof">Progress and report proof</SectionTitle>
            <p className="text-muted mt-1 max-w-[65ch] text-xs leading-relaxed">
              {data.resolved_actions.count} action(s) resolved since the comparable run. Metric
              movement is shown alongside completion without claiming causation.
            </p>
          </div>
          {data.report_available ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={onDownload}
              pending={downloading}
              pendingLabel="Preparing…"
              className="shrink-0 gap-1.5"
            >
              <Download className="size-4" aria-hidden /> Download PDF
            </Button>
          ) : null}
        </section>
      </div>
    </>
  );
}
