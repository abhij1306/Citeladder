'use client';

import { useMemo, useState } from 'react';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { ChevronDown, ChevronRight } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { CursorPager } from '@/components/ui/cursor-pager';
import {
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownLabel,
  DropdownRadioGroup,
  DropdownRadioItem,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import { AccentEyebrow } from '@/components/ui/eyebrow';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { EvidenceDrawer } from '@/components/opportunities/evidence-drawer';
import { OPPORTUNITY_STATUS_META } from '@/components/opportunities/opportunity-status-meta';
import { OpportunityStatusBadge } from '@/components/opportunities/opportunity-status-badge';
import { OpportunityTypeBadge } from '@/components/opportunities/opportunity-type-badge';
import { useUpdateOpportunityStatus } from '@/components/opportunities/use-opportunity-status';
import { opportunitiesQueries, type OpportunitiesParams } from '@/lib/api/opportunities';
import type {
  Opportunity,
  OpportunitiesPage,
  OpportunityDetail,
  OpportunitySeverity,
  OpportunityStatus,
  OpportunityType,
} from '@/lib/api/types';
import { severityBadgeValue, severityLabel } from '@/lib/site-health/issues';
import { formatAudited } from '@/lib/site-health/status';
import { useCursorStack } from '@/lib/site-health/use-cursor-stack';

const PAGE_LIMIT = 25;

/**
 * Recommendation catalog: next best action + ranked action table + drawer.
 *
 * Server-backed severity/type/status filter menus (never a client-side filter
 * over the current page), a recommendation-first view of the top result, the
 * server-owned priority order without exposing its formula score, a per-row
 * status dropdown, and drill-down into the evidence drawer.
 */

type TypeFilter = 'all' | OpportunityType;
type SeverityFilter = 'all' | OpportunitySeverity;
type StatusFilter = 'active' | OpportunityStatus;
type PathFilter = 'all' | 'owned' | 'earned';

const TYPE_FILTERS: ReadonlyArray<{ key: TypeFilter; label: string }> = [
  { key: 'all', label: 'All types' },
  { key: 'visibility', label: 'Visibility' },
  { key: 'site', label: 'Site' },
  { key: 'traffic', label: 'Traffic' },
  { key: 'topic', label: 'Topic' },
];

const SEVERITY_FILTERS: ReadonlyArray<{ key: SeverityFilter; label: string }> = [
  { key: 'all', label: 'All impact levels' },
  { key: 'critical', label: 'Critical' },
  { key: 'high', label: 'High' },
  { key: 'medium', label: 'Medium' },
  { key: 'low', label: 'Low' },
  { key: 'info', label: 'Informational' },
];

// Status labels come from the single source (evidence-drawer's meta record,
// in display order) so chips, the row dropdown, and the drawer never drift.
const STATUS_CHOICES: ReadonlyArray<{ value: OpportunityStatus; label: string }> = (
  Object.keys(OPPORTUNITY_STATUS_META) as OpportunityStatus[]
).map((value) => ({ value, label: OPPORTUNITY_STATUS_META[value].label }));

// The server's no-status-param default IS the active triage queue
// (open + in_progress), so the honest chip label is "Active".
const STATUS_FILTERS: ReadonlyArray<{ key: StatusFilter; label: string }> = [
  { key: 'active', label: 'Active' },
  ...STATUS_CHOICES.map(({ value, label }) => ({ key: value, label })),
];
const PATH_FILTERS: ReadonlyArray<{ key: PathFilter; label: string }> = [
  { key: 'all', label: 'All paths' },
  { key: 'owned', label: 'Owned' },
  { key: 'earned', label: 'Earned' },
];

function FilterMenu<T extends string>({
  label,
  value,
  options,
  onChange,
}: Readonly<{
  label: string;
  value: T;
  options: ReadonlyArray<{ key: T; label: string }>;
  onChange: (value: T) => void;
}>) {
  const selectedLabel = options.find((option) => option.key === value)?.label ?? value;
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <Button variant="secondary" size="sm" aria-label={`${label}: ${selectedLabel}`}>
          <span className="text-muted">{label}</span>
          <span>{selectedLabel}</span>
          <ChevronDown className="size-4" aria-hidden />
        </Button>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownLabel>{label}</DropdownLabel>
        <DropdownRadioGroup value={value} onValueChange={(nextValue) => onChange(nextValue as T)}>
          {options.map((option) => (
            <DropdownRadioItem key={option.key} value={option.key}>
              {option.label}
            </DropdownRadioItem>
          ))}
        </DropdownRadioGroup>
      </DropdownContent>
    </Dropdown>
  );
}

function FeaturedRecommendation({
  detail,
  onOpen,
}: Readonly<{ detail: OpportunityDetail; onOpen: () => void }>) {
  // The backend owns target presentation (target_label) — no client helper.
  const target = detail.target_label;
  return (
    <Card className="border-accent-border">
      <CardContent className="grid gap-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid min-w-0 gap-2">
            <AccentEyebrow>Next best action</AccentEyebrow>
            <h2 className="text-foreground text-xl">{detail.title}</h2>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant="status" value={severityBadgeValue(detail.severity)}>
                {severityLabel(detail.severity)} impact
              </Badge>
              <OpportunityTypeBadge type={detail.opportunity_type} />
              <OpportunityStatusBadge status={detail.status} />
            </div>
          </div>
          <Button size="sm" onClick={onOpen}>
            Review recommendation
            <ChevronRight className="size-4" aria-hidden />
          </Button>
        </div>
        <p className="text-secondary max-w-3xl text-sm whitespace-pre-line">{detail.remediation}</p>
        {target ? (
          <p className="text-muted min-w-0 truncate text-xs" title={target}>
            Applies to {target}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** Per-row status control (dropdown → updateStatus mutation). */
function StatusControl({ row, projectId }: Readonly<{ row: Opportunity; projectId: string }>) {
  const updateStatus = useUpdateOpportunityStatus(projectId, row.id);
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <button
          type="button"
          aria-label={`Change status for ${row.title}`}
          className="focus-ring rounded-full"
          // Row click opens the drawer — the status control must not.
          onClick={(event) => event.stopPropagation()}
        >
          <OpportunityStatusBadge status={row.status} />
        </button>
      </DropdownTrigger>
      <DropdownContent>
        {STATUS_CHOICES.map((choice) => (
          <DropdownItem
            key={choice.value}
            disabled={choice.value === row.status || updateStatus.isPending}
            onSelect={() => updateStatus.mutate({ opportunityId: row.id, status: choice.value })}
          >
            {choice.label}
          </DropdownItem>
        ))}
      </DropdownContent>
    </Dropdown>
  );
}

export function OpportunitiesCatalog({ projectId }: Readonly<{ projectId: string }>) {
  const filters = useCatalogFilters();
  const listQuery = useQuery(opportunitiesQueries.list(projectId, filters.params));
  const rows = listQuery.data?.items ?? [];
  const featured = useFeaturedRecommendation(rows, filters.statusFilter, filters.pager.cursor);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  return (
    <div className="grid gap-[var(--workspace-gap)]">
      <FeaturedSection featured={featured} onOpen={setSelectedId} />
      <RecommendationsSection
        projectId={projectId}
        filters={filters}
        listQuery={listQuery}
        rows={rows}
        onOpen={setSelectedId}
      />
      <EvidenceDrawer
        opportunityId={selectedId}
        projectId={projectId}
        open={selectedId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedId(null);
        }}
      />
    </div>
  );
}

function useCatalogFilters() {
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('active');
  const [pathFilter, setPathFilter] = useState<PathFilter>('all');
  const pager = useCursorStack();
  const params: OpportunitiesParams = useMemo(
    () => ({
      type: typeFilter === 'all' ? undefined : typeFilter,
      severity: severityFilter === 'all' ? undefined : severityFilter,
      status: statusFilter === 'active' ? undefined : statusFilter,
      action_path: pathFilter === 'all' ? undefined : pathFilter,
      cursor: pager.cursor,
      limit: PAGE_LIMIT,
    }),
    [typeFilter, severityFilter, statusFilter, pathFilter, pager.cursor],
  );
  const reset =
    <T,>(setter: (value: T) => void) =>
    (value: T) => {
      setter(value);
      pager.reset();
    };
  return {
    typeFilter,
    setTypeFilter: reset(setTypeFilter),
    severityFilter,
    setSeverityFilter: reset(setSeverityFilter),
    statusFilter,
    setStatusFilter: reset(setStatusFilter),
    pathFilter,
    setPathFilter: reset(setPathFilter),
    pager,
    params,
  };
}

function useFeaturedRecommendation(
  rows: Opportunity[],
  statusFilter: StatusFilter,
  cursor: string | undefined,
) {
  const featuredId = statusFilter === 'active' && !cursor ? (rows[0]?.id ?? null) : null;
  return useQuery({
    ...opportunitiesQueries.detail(featuredId ?? ''),
    enabled: featuredId !== null,
  });
}

function FeaturedSection({
  featured,
  onOpen,
}: Readonly<{
  featured: ReturnType<typeof useFeaturedRecommendation>;
  onOpen: (id: string) => void;
}>) {
  if (featured.isPending && !featured.data) return <Skeleton className="h-44 w-full" />;
  return featured.data ? (
    <FeaturedRecommendation detail={featured.data} onOpen={() => onOpen(featured.data.id)} />
  ) : null;
}

function RecommendationsSection({
  projectId,
  filters,
  listQuery,
  rows,
  onOpen,
}: Readonly<{
  projectId: string;
  filters: ReturnType<typeof useCatalogFilters>;
  listQuery: UseQueryResult<OpportunitiesPage, Error>;
  rows: Opportunity[];
  onOpen: (id: string) => void;
}>) {
  return (
    <section className="grid gap-3" aria-labelledby="recommendations-heading">
      <RecommendationsHeader filters={filters} />
      <RecommendationsBody projectId={projectId} query={listQuery} rows={rows} onOpen={onOpen} />
      {rows.length ? (
        <div className="flex items-center justify-end gap-2">
          <CursorPager
            canPrev={filters.pager.canPrev}
            canNext={Boolean(listQuery.data?.next_cursor)}
            onPrev={filters.pager.pop}
            onNext={() => filters.pager.push(listQuery.data?.next_cursor ?? null)}
          />
        </div>
      ) : null}
    </section>
  );
}

function RecommendationsHeader({
  filters,
}: Readonly<{ filters: ReturnType<typeof useCatalogFilters> }>) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="grid gap-1">
        <h2 id="recommendations-heading" className="text-foreground text-lg">
          Prioritized recommendations
        </h2>
        <p className="text-muted text-xs">
          Ordered by expected impact using your latest visibility and site evidence.
        </p>
      </div>
      <fieldset className="flex flex-wrap items-center gap-2" aria-label="Recommendation filters">
        <FilterMenu
          label="Path"
          value={filters.pathFilter}
          options={PATH_FILTERS}
          onChange={filters.setPathFilter}
        />
        <FilterMenu
          label="Area"
          value={filters.typeFilter}
          options={TYPE_FILTERS}
          onChange={filters.setTypeFilter}
        />
        <FilterMenu
          label="Impact"
          value={filters.severityFilter}
          options={SEVERITY_FILTERS}
          onChange={filters.setSeverityFilter}
        />
        <FilterMenu
          label="Status"
          value={filters.statusFilter}
          options={STATUS_FILTERS}
          onChange={filters.setStatusFilter}
        />
      </fieldset>
    </div>
  );
}

function RecommendationsBody({
  projectId,
  query,
  rows,
  onOpen,
}: Readonly<{
  projectId: string;
  query: UseQueryResult<OpportunitiesPage, Error>;
  rows: Opportunity[];
  onOpen: (id: string) => void;
}>) {
  if (query.isError && !query.data)
    return <Alert tone="danger">Could not load opportunities. Please refresh.</Alert>;
  if (query.isPending && !query.data)
    return (
      <div className="grid gap-3">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  if (!rows.length)
    return (
      <Card>
        <CardContent className="text-secondary text-sm">
          No recommendations match these filters. Try broadening the area, impact, or status.
        </CardContent>
      </Card>
    );
  return <RecommendationsTable projectId={projectId} rows={rows} onOpen={onOpen} />;
}

function RecommendationsTable({
  projectId,
  rows,
  onOpen,
}: Readonly<{ projectId: string; rows: Opportunity[]; onOpen: (id: string) => void }>) {
  return (
    <Card>
      <Table className="min-w-3xl table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead className="w-[48%]">Recommendation</TableHead>
            <TableHead>Impact</TableHead>
            <TableHead>Area</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Detected</TableHead>
            <TableHead className="w-24" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id} className="hover:bg-background-alt">
              <TableCell className="min-w-0">
                <div className="grid min-w-0 gap-0.5">
                  <span className="text-foreground truncate text-sm font-medium" title={row.title}>
                    {row.title}
                  </span>
                  {row.target_label ? (
                    <span className="text-2xs text-muted truncate" title={row.target_label}>
                      {row.target_label}
                    </span>
                  ) : null}
                </div>
              </TableCell>
              <TableCell>
                <Badge variant="status" value={severityBadgeValue(row.severity)}>
                  {severityLabel(row.severity)}
                </Badge>
              </TableCell>
              <TableCell>
                <OpportunityTypeBadge type={row.opportunity_type} />
              </TableCell>
              <TableCell>
                <StatusControl row={row} projectId={projectId} />
              </TableCell>
              <TableCell>
                <span className="text-secondary text-xs whitespace-nowrap">
                  {formatAudited(row.created_at)}
                </span>
              </TableCell>
              <TableCell>
                <Button variant="ghost" size="sm" onClick={() => onOpen(row.id)}>
                  Review
                  <ChevronRight className="size-4" aria-hidden />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}
