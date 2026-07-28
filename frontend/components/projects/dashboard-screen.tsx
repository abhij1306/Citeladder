'use client';

import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  Download,
  Gauge,
  HeartPulse,
  Lightbulb,
  ListChecks,
  LoaderCircle,
  MessageSquareText,
  Plus,
  ShoppingBag,
  BookOpen,
  CircleAlert,
  FolderOpen,
  PenLine,
  Play,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { BrandLogo } from '@/components/ui/brand-logo';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { IconChip } from '@/components/ui/icon-chip';
import { scoreTextClass } from '@/components/ui/score-band';
import { Skeleton } from '@/components/ui/skeleton';
import { projectsApi } from '@/lib/api/projects';
import { queryKeys } from '@/lib/api/query-keys';
import type { DashboardSection, DashboardSectionState } from '@/lib/api/types';
import { useProjectContext } from '@/lib/project/project-context';
import { cn } from '@/lib/utils';

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(1);
  if (typeof value === 'boolean') return value ? 'Configured' : 'Not configured';
  if (typeof value === 'string') return value.replaceAll('_', ' ');
  return 'Available';
}

/** The first non-null metric, split into label + value for the stat layout. */
function primaryMetric(section: DashboardSection): { label: string; value: unknown } | null {
  const entries = Object.entries(section.metrics).filter(([, value]) => value !== null);
  if (entries.length === 0) return null;
  const [name, value] = entries[0];
  return { label: name.replaceAll('_', ' '), value };
}

function hasDashboardSignal(section: DashboardSection) {
  return (
    section.state === 'ready' || section.state === 'running' || primaryMetric(section) !== null
  );
}

/** Every dashboard section owns a glyph; the chip tint comes from the accent. */
const SECTION_ICONS: Record<DashboardSection['id'], LucideIcon> = {
  visibility: Gauge,
  answers: MessageSquareText,
  traffic: TrendingUp,
  prompts: ListChecks,
  commerce: ShoppingBag,
  runs: Play,
  content: PenLine,
  site_health: HeartPulse,
  issues: CircleAlert,
  opportunities: Lightbulb,
  brand_knowledge: BookOpen,
  projects: FolderOpen,
};

/** State → badge tone. Colour carries meaning only (WCAG 1.4.1: the label always renders). */
const SECTION_STATE_BADGE: Record<
  DashboardSectionState,
  { variant: 'status'; value: 'success' | 'info' | 'warning' | 'danger' } | { variant: 'neutral' }
> = {
  ready: { variant: 'status', value: 'success' },
  running: { variant: 'status', value: 'info' },
  not_setup: { variant: 'status', value: 'warning' },
  failed: { variant: 'status', value: 'danger' },
  empty: { variant: 'neutral' },
};

function SectionCard({ section }: Readonly<{ section: DashboardSection }>) {
  const Icon = SECTION_ICONS[section.id];
  const metric = primaryMetric(section);
  const badge = SECTION_STATE_BADGE[section.state];
  return (
    <Link
      href={section.href}
      data-tour={`dashboard-${section.id}`}
      className="focus-ring group block rounded-lg"
      aria-label={`Open ${section.title}`}
    >
      {/* Interactive card: rests on the raised rung, lifts to the overlay
          rung and rises 2px on hover — the ADS surface/shadow pairing. */}
      <Card className="group-hover:shadow-card-hover h-full transition-[box-shadow,transform] duration-200 group-hover:-translate-y-0.5">
        <CardHeader className="gap-2">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-3">
              <IconChip className="shrink-0">
                <Icon className="size-6" />
              </IconChip>
              <CardTitle>{section.title}</CardTitle>
            </div>
            {badge.variant === 'status' ? (
              <Badge variant="status" value={badge.value} className="capitalize">
                {section.state.replaceAll('_', ' ')}
              </Badge>
            ) : (
              <Badge className="capitalize">{section.state.replaceAll('_', ' ')}</Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="flex items-end justify-between gap-2 pt-0">
          {metric ? (
            <p className="grid gap-0.5">
              <span
                className={cn(
                  'mono text-lg',
                  typeof metric.value === 'number' && metric.label.includes('score')
                    ? scoreTextClass(metric.value)
                    : 'text-foreground',
                )}
              >
                {displayValue(metric.value)}
              </span>
              <span className="text-muted text-xs capitalize">{metric.label}</span>
            </p>
          ) : (
            <p className="text-muted text-sm capitalize">{section.state.replaceAll('_', ' ')}</p>
          )}
          <ArrowRight
            aria-hidden
            className="text-muted group-hover:text-accent-text size-4 shrink-0 transition-[color,transform] duration-200 group-hover:translate-x-0.5"
          />
        </CardContent>
      </Card>
    </Link>
  );
}

function MetricTile({
  label,
  value,
  icon: Icon,
  score = false,
}: Readonly<{ label: string; value: unknown; icon: LucideIcon; score?: boolean }>) {
  const numeric = typeof value === 'number' ? value : null;
  return (
    <Card>
      <CardContent className="grid gap-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-muted text-xs">{label}</p>
          <IconChip>
            <Icon className="size-6" />
          </IconChip>
        </div>
        <p
          className={cn(
            'mono text-2xl leading-none',
            score ? scoreTextClass(numeric) : numeric === null ? 'text-muted' : 'text-foreground',
          )}
        >
          {displayValue(value)}
        </p>
      </CardContent>
    </Card>
  );
}

function DashboardSkeleton() {
  return (
    <div className="grid gap-6" aria-hidden>
      <Skeleton className="h-8 w-64" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    </div>
  );
}

/** Active-project landing view backed exclusively by the persisted Dashboard projection. */
export function DashboardScreen() {
  const { activeProject, isLoading } = useProjectContext();
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState(false);
  const dashboard = useQuery({
    queryKey: queryKeys.projects.dashboard(activeProject?.id ?? ''),
    queryFn: ({ signal }) => projectsApi.getDashboard(activeProject!.id, { signal }),
    enabled: Boolean(activeProject),
  });

  const downloadReport = async () => {
    if (!activeProject) return;
    setDownloadError(false);
    setDownloading(true);
    try {
      const blob = await projectsApi.downloadDashboardReport(activeProject.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `searchify-${activeProject.brand_name || activeProject.name}-report.pdf`;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch {
      setDownloadError(true);
    } finally {
      setDownloading(false);
    }
  };

  if (isLoading) {
    return <DashboardSkeleton />;
  }
  if (!activeProject) {
    return (
      <Card>
        <CardContent className="grid gap-3">
          <CardTitle>Start with a project</CardTitle>
          <CardDescription>Create a brand to activate your Dashboard.</CardDescription>
          <Button asChild className="w-fit">
            <Link href="/onboarding?new=1">
              <Plus className="size-4" aria-hidden />
              Add project
            </Link>
          </Button>
        </CardContent>
      </Card>
    );
  }
  if (dashboard.isLoading) return <DashboardSkeleton />;
  if (dashboard.isError || !dashboard.data) {
    return (
      <Alert tone="danger">
        Could not load the Dashboard.{' '}
        <Button variant="ghost" size="sm" onClick={() => dashboard.refetch()}>
          Try again
        </Button>
      </Alert>
    );
  }

  const { data } = dashboard;
  const visibility = data.analyze.find((section) => section.id === 'visibility');
  const analyzeSections = data.analyze.filter(
    (section) =>
      !(section.id === 'visibility' && section.state === 'empty') && hasDashboardSignal(section),
  );
  const improveSections = data.improve.filter(
    (section) => section.id !== 'projects' && hasDashboardSignal(section),
  );
  const generatedAt = new Date(data.generated_at);
  return (
    <div className="grid gap-6" data-tour="dashboard-overview">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <BrandLogo
            name={data.project.brand_name || data.project.name}
            websiteUrl={data.project.website_url}
            size="md"
          />
          <div>
            <h2 className="text-foreground text-xl">
              {data.project.brand_name || data.project.name}
            </h2>
            <p className="text-muted mt-1 text-sm">
              A live summary of your Searchify results · Snapshot{' '}
              {generatedAt.toLocaleString(undefined, {
                dateStyle: 'medium',
                timeStyle: 'short',
              })}
            </p>
          </div>
        </div>
        <Button
          variant="secondary"
          onClick={downloadReport}
          disabled={downloading}
          data-tour="dashboard-report"
        >
          {downloading ? (
            <LoaderCircle className="size-4 animate-spin" aria-hidden />
          ) : (
            <Download className="size-4" aria-hidden />
          )}
          {downloading ? 'Preparing…' : 'Download report'}
        </Button>
      </div>

      {downloadError ? (
        <Alert tone="danger">Could not download the report. Please try again.</Alert>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile
          label="Visibility score"
          value={data.executive_metrics.visibility_score}
          icon={Gauge}
          score
        />
        <MetricTile
          label="Site health"
          value={data.executive_metrics.site_health_score}
          icon={HeartPulse}
          score
        />
        <MetricTile
          label="Open opportunities"
          value={data.executive_metrics.open_opportunities}
          icon={Lightbulb}
        />
        <MetricTile
          label="Active prompts"
          value={data.executive_metrics.active_prompts}
          icon={ListChecks}
        />
      </div>

      {visibility?.state === 'empty' ? (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-4">
            <div className="grid gap-1">
              <h2 className="text-foreground text-heading-sm">Start measuring visibility</h2>
              <p className="text-secondary text-sm">
                Connect an answer-engine provider, then launch your first audit to populate this
                dashboard.
              </p>
            </div>
            <Button asChild variant="secondary" className="shrink-0">
              <Link href="/settings?tab=providers">
                Connect providers
                <ArrowRight className="size-4" aria-hidden />
              </Link>
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {data.active_work.length > 0 ? (
        <Alert tone="info">
          Active work: {data.active_work.map((item) => item.replaceAll('_', ' ')).join(', ')}.
        </Alert>
      ) : null}

      {analyzeSections.length > 0 ? (
        <section aria-labelledby="dashboard-analyze">
          <h2 id="dashboard-analyze" className="text-foreground text-heading-sm mb-3">
            Analyze
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {analyzeSections.map((section) => (
              <SectionCard key={section.id} section={section} />
            ))}
          </div>
        </section>
      ) : null}

      {improveSections.length > 0 ? (
        <section aria-labelledby="dashboard-improve">
          <h2 id="dashboard-improve" className="text-foreground text-heading-sm mb-3">
            Improve
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {improveSections.map((section) => (
              <SectionCard key={section.id} section={section} />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
