/**
 * Site Health inventory + issue filter serialization (Task 2) — PURE.
 *
 * Serializes the inventory and issue filter models to/from URL query state so
 * filters/cursors live in the address bar (shareable, restorable). Ordering is
 * URL-only in this release, so there is no sort field to serialize. The cursor
 * is opaque and filter-bound on the server — reusing a cursor with changed
 * filters is rejected server-side, so this module DROPS the cursor whenever a
 * filter changes (see `changeInventoryFilters`).
 */
import type { InventoryParams, IssuesParams } from '@/lib/api/site-health';

/** The `monitored=` tri-state as it appears in the inventory URL. */
type MonitoredFilter = 'all' | 'monitored' | 'unmonitored';

/** Inventory filter model (drives the inventory query + URL state). */
export type InventoryFilters = {
  query: string;
  status: string;
  monitored: MonitoredFilter;
  /** v2 P1 page-kind filter ('' = all types). */
  page_kind: string;
};

export const emptyInventoryFilters: InventoryFilters = {
  query: '',
  status: '',
  monitored: 'all',
  page_kind: '',
};

/** Issue filter model (drives the issues query + URL state). */
export type IssueFilters = {
  query: string;
  severity: string;
  category: string;
  dimension: string;
  rule_id: string;
  site_url_id: string;
  finding_class: 'defect' | 'advisory';
  /** v2 P1 page-kind filter ('' = all types). */
  page_kind: string;
};

export const emptyIssueFilters: IssueFilters = {
  query: '',
  severity: '',
  category: '',
  dimension: '',
  rule_id: '',
  site_url_id: '',
  finding_class: 'defect',
  page_kind: '',
};

function monitoredToParam(monitored: MonitoredFilter): boolean | undefined {
  if (monitored === 'monitored') return true;
  if (monitored === 'unmonitored') return false;
  return undefined;
}

function monitoredFromParam(value: string | null | undefined): MonitoredFilter {
  if (value === 'true') return 'monitored';
  if (value === 'false') return 'unmonitored';
  return 'all';
}

/** Build inventory request params (undefined fields are dropped downstream). */
export function toInventoryParams(
  filters: InventoryFilters,
  cursor?: string | null,
  limit?: number,
): InventoryParams {
  return {
    cursor: cursor ?? undefined,
    limit,
    query: filters.query.trim() || undefined,
    status: filters.status || undefined,
    monitored: monitoredToParam(filters.monitored),
    page_kind: filters.page_kind || undefined,
  };
}

/** Serialize inventory filters (+ optional cursor) to a URLSearchParams. */
export function serializeInventoryFilters(
  filters: InventoryFilters,
  cursor?: string | null,
): URLSearchParams {
  const params = new URLSearchParams();
  const query = filters.query.trim();
  if (query) params.set('query', query);
  if (filters.status) params.set('status', filters.status);
  if (filters.monitored !== 'all')
    params.set('monitored', String(monitoredToParam(filters.monitored)));
  if (filters.page_kind) params.set('page_kind', filters.page_kind);
  if (cursor) params.set('cursor', cursor);
  return params;
}

/** Parse inventory filters back from URL query state (round-trips exactly). */
export function parseInventoryFilters(params: URLSearchParams): InventoryFilters {
  return {
    query: params.get('query') ?? '',
    status: params.get('status') ?? '',
    monitored: monitoredFromParam(params.get('monitored')),
    page_kind: params.get('page_kind') ?? '',
  };
}

/** Extract an opaque cursor from URL query state (null when absent). */
export function parseCursor(params: URLSearchParams): string | null {
  return params.get('cursor');
}

/**
 * Apply a filter change, DROPPING any active cursor. Filter-bound cursors are
 * rejected server-side once filters differ, so a filter edit always restarts
 * from the first page.
 */
export function changeInventoryFilters(
  _current: InventoryFilters,
  next: Partial<InventoryFilters>,
  base: InventoryFilters = _current,
): { filters: InventoryFilters; cursor: null } {
  return { filters: { ...base, ...next }, cursor: null };
}

/** True when two inventory filter models are equivalent (cursor validity). */
export function inventoryFiltersEqual(a: InventoryFilters, b: InventoryFilters): boolean {
  return (
    a.query.trim() === b.query.trim() &&
    a.status === b.status &&
    a.monitored === b.monitored &&
    a.page_kind === b.page_kind
  );
}

/** Build issue request params. */
export function toIssueParams(
  filters: IssueFilters,
  cursor?: string | null,
  limit?: number,
): IssuesParams {
  return {
    cursor: cursor ?? undefined,
    limit,
    query: filters.query.trim() || undefined,
    severity: filters.severity || undefined,
    category: filters.category || undefined,
    dimension: filters.dimension || undefined,
    // The backend issues endpoint names the rule filter `rule` (not `rule_id`);
    // the `IssueFilters` model keeps `rule_id` as its internal URL-state key.
    rule: filters.rule_id || undefined,
    site_url_id: filters.site_url_id || undefined,
    finding_class: filters.finding_class,
    page_kind: filters.page_kind || undefined,
  };
}

/** Serialize issue filters (+ optional cursor) to a URLSearchParams. */
export function serializeIssueFilters(
  filters: IssueFilters,
  cursor?: string | null,
  base?: URLSearchParams,
): URLSearchParams {
  const params = new URLSearchParams(base);
  for (const key of [
    'query',
    'severity',
    'category',
    'dimension',
    'rule',
    'rule_id',
    'site_url_id',
    'finding_class',
    'page_kind',
    'cursor',
  ]) {
    params.delete(key);
  }
  const query = filters.query.trim();
  if (query) params.set('query', query);
  if (filters.severity) params.set('severity', filters.severity);
  if (filters.category) params.set('category', filters.category);
  if (filters.dimension) params.set('dimension', filters.dimension);
  if (filters.rule_id) params.set('rule', filters.rule_id);
  if (filters.site_url_id) params.set('site_url_id', filters.site_url_id);
  if (filters.finding_class !== 'defect') params.set('finding_class', filters.finding_class);
  if (filters.page_kind) params.set('page_kind', filters.page_kind);
  if (cursor) params.set('cursor', cursor);
  return params;
}

/** Parse issue filters back from URL query state. */
export function parseIssueFilters(params: URLSearchParams): IssueFilters {
  return {
    query: params.get('query') ?? '',
    severity: params.get('severity') ?? '',
    category: params.get('category') ?? '',
    dimension: params.get('dimension') ?? '',
    rule_id: params.get('rule') ?? params.get('rule_id') ?? '',
    site_url_id: params.get('site_url_id') ?? '',
    finding_class: params.get('finding_class') === 'advisory' ? 'advisory' : 'defect',
    page_kind: params.get('page_kind') ?? '',
  };
}

/** Apply an issue-filter change, dropping the cursor. */
export function changeIssueFilters(
  current: IssueFilters,
  next: Partial<IssueFilters>,
): { filters: IssueFilters; cursor: null } {
  return { filters: { ...current, ...next }, cursor: null };
}

/** True when two issue filter models are equivalent. */
export function issueFiltersEqual(a: IssueFilters, b: IssueFilters): boolean {
  return (
    a.severity === b.severity &&
    a.query.trim() === b.query.trim() &&
    a.category === b.category &&
    a.dimension === b.dimension &&
    a.rule_id === b.rule_id &&
    a.site_url_id === b.site_url_id &&
    a.finding_class === b.finding_class &&
    a.page_kind === b.page_kind
  );
}
