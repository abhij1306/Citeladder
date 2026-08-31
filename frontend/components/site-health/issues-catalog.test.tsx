import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';
import type { IssueOccurrence, SiteIssue } from '@/lib/api/types';
import { IssuesCatalog } from './issues-catalog';

const navigation = vi.hoisted(() => {
  let entries = [''];
  let index = 0;
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach((listener) => listener());
  const set = (search: string) => {
    entries = [search.replace(/^\?/, '')];
    index = 0;
    notify();
  };
  const push = vi.fn((href: string) => {
    const search = href.split('?')[1] ?? '';
    entries = [...entries.slice(0, index + 1), search];
    index += 1;
    notify();
  });
  return {
    back: () => {
      if (index > 0) index -= 1;
      notify();
    },
    forward: () => {
      if (index < entries.length - 1) index += 1;
      notify();
    },
    get: () => entries[index] ?? '',
    listeners,
    push,
    set,
  };
});

vi.mock('next/navigation', async () => {
  const { useSyncExternalStore } = await import('react');
  return {
    usePathname: () => '/issues',
    useRouter: () => ({ push: navigation.push }),
    useSearchParams: () => {
      const search = useSyncExternalStore(
        (listener) => {
          navigation.listeners.add(listener);
          return () => navigation.listeners.delete(listener);
        },
        navigation.get,
        navigation.get,
      );
      return new URLSearchParams(search);
    },
  };
});

const CRAWL = '44444444-4444-4444-8444-444444444444';
const ISSUE_A = 'aaaaaaaa-1111-4111-8111-111111111111';
const URL_A = 'cccccccc-1111-4111-8111-111111111111';

function issue(overrides: Partial<SiteIssue> = {}): SiteIssue {
  return {
    group_id: ISSUE_A,
    crawl_id: CRAWL,
    rule_id: 'aeo.website_schema',
    page_kinds: [],
    dimension: 'aeo',
    category: 'schema',
    severity: 'high',
    finding_class: 'defect',
    title: 'WebSite schema is missing',
    description: 'Search engines cannot find WebSite structured data on this page.',
    remediation: 'Add a JSON-LD WebSite schema.',
    affected_url_count: 32,
    analyzer_version: 'a1',
    rule_version: 'r1',
    created_at: '2026-07-15T00:00:00Z',
    ...overrides,
  };
}

function occurrence(overrides: Partial<IssueOccurrence> = {}): IssueOccurrence {
  return {
    occurrence_id: 'dddddddd-1111-4111-8111-111111111111',
    evaluation_id: 'eeeeeeee-1111-4111-8111-111111111111',
    crawl_id: CRAWL,
    rule_id: 'aeo.website_schema',
    site_url_id: URL_A,
    normalized_url: 'https://acme.com/',
    display_url: 'https://acme.com/',
    title: 'Homepage',
    page_kind: 'article',
    dimension: 'aeo',
    category: 'schema',
    severity: 'high',
    finding_class: 'defect',
    issue_title: 'WebSite schema is missing',
    description: 'Expected WebSite structured data is absent.',
    remediation: 'Add a JSON-LD WebSite schema.',
    reason_code: 'expected_schema_absent',
    evidence: { expected_types: ['WebSite'], found_types: ['Organization'] },
    analyzer_version: 'a1',
    rule_version: 'r1',
    created_at: '2026-07-15T00:00:00Z',
    ...overrides,
  };
}

function issueDetail(overrides: Record<string, unknown> = {}) {
  return {
    group_id: ISSUE_A,
    crawl_id: CRAWL,
    rule_id: 'aeo.website_schema',
    dimension: 'aeo',
    category: 'schema',
    severity: 'high',
    finding_class: 'defect',
    title: 'WebSite schema is missing',
    description: 'Search engines cannot find WebSite structured data on this page.',
    remediation: 'Add a JSON-LD WebSite schema.',
    occurrences: [occurrence()],
    occurrence_count: 1,
    affected_url_count: 1,
    analyzer_version: 'a1',
    rule_version: 'r1',
    created_at: '2026-07-15T00:00:00Z',
    next_cursor: null,
    ...overrides,
  };
}

const summary = {
  issue_count: 47,
  defect_issue_type_count: 47,
  advisory_issue_type_count: 2,
  occurrence_count: 94,
  severity_counts: { high: 12, medium: 23, low: 12 },
  dimension_counts: { technical: 30, aeo: 17 },
  affected_url_count: 50,
  monitored_affected_url_count: 38,
};

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
beforeEach(() => {
  navigation.set('');
  navigation.push.mockClear();
  mswServer.use(
    http.get(`/api/v1/site-crawls/${CRAWL}/issues/${ISSUE_A}`, () =>
      HttpResponse.json(issueDetail()),
    ),
  );
});
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('IssuesCatalog', () => {
  it('seeds the server query from an Overview rule deep link', async () => {
    const seen: URLSearchParams[] = [];
    navigation.set(
      'rule=aeo.website_schema&dimension=aeo&query=schema&page_kind=article&cursor=page-two&campaign=overview',
    );
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/issues`, ({ request }) => {
        seen.push(new URL(request.url).searchParams);
        return HttpResponse.json({ items: [issue()], next_cursor: null, summary });
      }),
    );

    renderWithProviders(<IssuesCatalog crawlId={CRAWL} />);

    expect(await screen.findAllByText('WebSite schema is missing')).not.toHaveLength(0);
    expect(screen.getByRole('button', { name: 'First page' })).not.toBeDisabled();
    expect(seen.at(-1)?.get('rule')).toBe('aeo.website_schema');
    expect(seen.at(-1)?.get('dimension')).toBe('aeo');
    expect(seen.at(-1)?.get('query')).toBe('schema');
    expect(seen.at(-1)?.get('page_kind')).toBe('article');
    expect(seen.at(-1)?.get('cursor')).toBe('page-two');
    expect(screen.getByRole('searchbox', { name: 'Search issues' })).toHaveValue('schema');
    expect(screen.getByRole('radio', { name: 'AEO (17)' })).toHaveAttribute('aria-checked', 'true');
  });

  it('writes filters to history and reflects back/forward navigation', async () => {
    navigation.set('rule=aeo.website_schema&campaign=overview');
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/issues`, () =>
        HttpResponse.json({ items: [issue()], next_cursor: null, summary }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<IssuesCatalog crawlId={CRAWL} />);
    await screen.findAllByText('WebSite schema is missing');

    await user.click(screen.getByRole('radio', { name: 'Medium (23)' }));
    await waitFor(() => expect(navigation.get()).toContain('severity=medium'));
    expect(navigation.get()).toContain('rule=aeo.website_schema');
    expect(navigation.get()).toContain('campaign=overview');

    act(() => navigation.back());
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: 'All (47)' })).toHaveAttribute(
        'aria-checked',
        'true',
      ),
    );
    expect(navigation.get()).not.toContain('severity=medium');

    act(() => navigation.forward());
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: 'Medium (23)' })).toHaveAttribute(
        'aria-checked',
        'true',
      ),
    );
  });

  it('drops a filter-bound cursor while preserving unknown URL params', async () => {
    navigation.set('cursor=page-two&campaign=overview');
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/issues`, () =>
        HttpResponse.json({ items: [issue()], next_cursor: null, summary }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<IssuesCatalog crawlId={CRAWL} />);
    const trigger = await screen.findByRole('button', { name: 'Filter by page kind' });

    await user.click(trigger);
    await user.click(await screen.findByRole('menuitemradio', { name: 'Article' }));

    await waitFor(() => expect(navigation.get()).toContain('page_kind=article'));
    expect(navigation.get()).not.toContain('cursor=');
    expect(navigation.get()).toContain('campaign=overview');
  });

  it('renders the API-owned summary and grouped issue rows', async () => {
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/issues`, () =>
        HttpResponse.json({ items: [issue()], next_cursor: null, summary }),
      ),
    );

    renderWithProviders(<IssuesCatalog crawlId={CRAWL} />);

    expect(await screen.findAllByText('WebSite schema is missing')).not.toHaveLength(0);
    // Chip counts (tiles removed): All (47), Medium (23), AEO (17). The counts
    // come from the API-owned summary, not a client re-count.
    expect(screen.getByRole('radio', { name: 'All (47)' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Medium (23)' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'AEO (17)' })).toBeInTheDocument();
    // Severity + dimension badges + affected-count copy.
    expect(screen.getAllByText('HIGH')).toHaveLength(2);
    expect(screen.getAllByText('AEO').length).toBeGreaterThan(0);
    expect(screen.getByText('32 pages affected')).toBeInTheDocument();
    expect(
      screen.getAllByText('Search engines cannot find WebSite structured data on this page.'),
    ).toHaveLength(2);
    expect(await screen.findByText('Expected WebSite; found Organization.')).toBeInTheDocument();
    expect(screen.queryByText('Reason: expected_schema_absent')).not.toBeInTheDocument();
    expect(screen.getByText('Add a JSON-LD WebSite schema.')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'WebSite schema is missing' }).closest('section'),
    ).toHaveClass(
      'lg:max-h-[calc(100dvh-var(--topbar-height)-2*var(--workspace-gap))]',
      'lg:overflow-hidden',
    );
    // No unsupported "mark reviewed/resolved" action is rendered.
    expect(screen.queryByText(/mark reviewed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/mark resolved/i)).not.toBeInTheDocument();
  });

  it('applies a severity filter as a server param (not a client filter)', async () => {
    const seen: string[] = [];
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/issues`, ({ request }) => {
        const url = new URL(request.url);
        seen.push(url.searchParams.get('severity') ?? '');
        return HttpResponse.json({ items: [issue()], next_cursor: null, summary });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<IssuesCatalog crawlId={CRAWL} />);
    await screen.findAllByText('WebSite schema is missing');

    await user.click(screen.getByRole('radio', { name: 'Medium (23)' }));
    await waitFor(() => expect(seen).toContain('medium'));
  });

  it('keeps advisories in their own server-backed view and labels all quantities', async () => {
    const seen: Array<string | null> = [];
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/issues`, ({ request }) => {
        const findingClass = new URL(request.url).searchParams.get('finding_class');
        seen.push(findingClass);
        return HttpResponse.json({
          items:
            findingClass === 'advisory'
              ? [
                  issue({
                    rule_id: 'technical.title_length_band',
                    title: 'Title length outside recommended band',
                    finding_class: 'advisory',
                    severity: 'low',
                  }),
                ]
              : [issue()],
          next_cursor: null,
          summary,
        });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<IssuesCatalog crawlId={CRAWL} />);
    expect(
      await screen.findByText((_, element) => element?.textContent === '47 defect issue types'),
    ).toBeInTheDocument();
    expect(
      screen.getByText((_, element) => element?.textContent === '94 defect occurrences'),
    ).toBeInTheDocument();
    expect(
      screen.getByText((_, element) => element?.textContent === '50 affected URLs'),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: 'Advisories (2)' }));
    expect(await screen.findAllByText('Title length outside recommended band')).not.toHaveLength(0);
    expect(screen.getAllByText('Advisory')).toHaveLength(2);
    expect(
      screen.getByText((_, element) => element?.textContent === '2 advisory issue types'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: /High/ })).not.toBeInTheDocument();
    expect(
      screen.getByText((_, element) => element?.textContent === '94 advisory occurrences'),
    ).toBeInTheDocument();
    expect(seen).toContain('advisory');
  });

  it('wires the page-kind filter as a server param, set and cleared', async () => {
    const seen: Array<string | null> = [];
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/issues`, ({ request }) => {
        seen.push(new URL(request.url).searchParams.get('page_kind'));
        return HttpResponse.json({ items: [issue()], next_cursor: null, summary });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<IssuesCatalog crawlId={CRAWL} />);
    const trigger = await screen.findByRole('button', { name: 'Filter by page kind' });
    // The initial unfiltered request carries no page-kind param.
    await screen.findAllByText('WebSite schema is missing');
    expect(seen.at(-1)).toBeNull();

    await user.click(trigger);
    await user.click(await screen.findByRole('menuitemradio', { name: 'Article' }));
    await waitFor(() => expect(seen.at(-1)).toBe('article'));

    // Clearing back to "All page kinds" drops the param entirely. The
    // unfiltered combination is already cached (no new request), so force a
    // fresh combination via a chip and assert THAT request omits page_kind.
    await user.click(trigger);
    await user.click(await screen.findByRole('menuitemradio', { name: 'All page kinds' }));
    await user.click(screen.getByRole('radio', { name: 'Medium (23)' }));
    await waitFor(() => expect(seen.at(-1)).toBeNull());
  });

  it('uses the selected issue right rail and links each occurrence to page detail', async () => {
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/issues`, () =>
        HttpResponse.json({ items: [issue()], next_cursor: null, summary }),
      ),
      http.get(`/api/v1/site-crawls/${CRAWL}/issues/${ISSUE_A}`, () =>
        HttpResponse.json(issueDetail()),
      ),
    );

    const user = userEvent.setup();
    renderWithProviders(<IssuesCatalog crawlId={CRAWL} />);
    await screen.findAllByText('WebSite schema is missing');

    await user.click(screen.getByRole('button', { name: /WebSite schema is missing/ }));
    await waitFor(() => expect(navigation.get()).toContain(`issue=${ISSUE_A}`));

    expect(await screen.findByText('Add a JSON-LD WebSite schema.')).toBeInTheDocument();
    const link = await screen.findByRole('link', { name: /Homepage/ });
    expect(link).toHaveAttribute('href', `/site/crawls/${CRAWL}/pages/${URL_A}`);
    // The affected page's v2 P1 type badge renders inside the row (scoped —
    // the filter <select> also lists the type label as an option).
    expect(within(link).getByText('Article')).toBeInTheDocument();
  });

  it('pages occurrences with a cursor-aware Next/Previous control', async () => {
    const seenCursors: (string | null)[] = [];
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/issues`, () =>
        HttpResponse.json({ items: [issue()], next_cursor: 'catalog-page-2', summary }),
      ),
      http.get(`/api/v1/site-crawls/${CRAWL}/issues/${ISSUE_A}`, ({ request }) => {
        const url = new URL(request.url);
        const cursor = url.searchParams.get('cursor');
        seenCursors.push(cursor);
        const onFirstPage = cursor === null;
        return HttpResponse.json(
          issueDetail({
            occurrences: [
              occurrence({
                occurrence_id: onFirstPage
                  ? 'dddddddd-1111-4111-8111-111111111111'
                  : 'dddddddd-2222-4111-8111-111111111111',
                site_url_id: onFirstPage ? URL_A : 'cccccccc-2222-4111-8111-111111111111',
                normalized_url: onFirstPage ? 'https://acme.com/' : 'https://acme.com/page-2',
                display_url: onFirstPage ? 'https://acme.com/' : 'https://acme.com/page-2',
                title: onFirstPage ? 'Homepage' : 'Page Two',
              }),
            ],
            occurrence_count: 2,
            affected_url_count: 2,
            next_cursor: onFirstPage ? 'cursor-page-2' : null,
          }),
        );
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<IssuesCatalog crawlId={CRAWL} />);
    await screen.findAllByText('WebSite schema is missing');

    await screen.findByRole('link', { name: /Homepage/ });

    const innerPrev = screen.getByRole('button', { name: 'Previous' });
    const [innerNext] = screen.getAllByRole('button', { name: 'Next' });
    expect(innerPrev).toBeDisabled();
    expect(innerNext).not.toBeDisabled();

    await user.click(innerNext);
    await screen.findByRole('link', { name: /Page Two/ });
    expect(seenCursors).toEqual([null, 'cursor-page-2']);
    const innerPrevAfterNext = screen.getByRole('button', { name: 'Previous' });
    const [innerNextAfterNext] = screen.getAllByRole('button', { name: 'Next' });
    expect(innerPrevAfterNext).not.toBeDisabled();
    expect(innerNextAfterNext).toBeDisabled();

    await user.click(innerPrevAfterNext);
    await screen.findByRole('link', { name: /Homepage/ });
    // Going back to cursor=null is served from the TanStack Query cache
    // (already fetched above), so no new request is issued — seenCursors
    // stays at the two requests already made.
    expect(seenCursors).toEqual([null, 'cursor-page-2']);

    await user.click(screen.getAllByRole('button', { name: 'Next' })[0]!);
    await screen.findByRole('link', { name: /Page Two/ });
    await user.click(screen.getAllByRole('button', { name: 'Next' })[1]!);
    await waitFor(() => expect(navigation.get()).toContain('cursor=catalog-page-2'));
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();

    await user.click(screen.getAllByRole('button', { name: 'Next' })[0]!);
    await screen.findByRole('link', { name: /Page Two/ });
    await user.click(screen.getByRole('button', { name: 'First page' }));
    await waitFor(() => expect(navigation.get()).not.toContain('cursor='));
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
  });

  it('shows which page types an issue affects, and says nothing when it spans none', async () => {
    // The product question this answers: a Product/offers finding scoped to
    // product pages is different work from a title finding that touches every
    // page, and the affected-page COUNT alone cannot tell them apart.
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/issues`, () =>
        HttpResponse.json({
          items: [issue({ page_kinds: ['product', 'category'] })],
          next_cursor: null,
          summary,
        }),
      ),
    );

    renderWithProviders(<IssuesCatalog crawlId={CRAWL} />);

    // Scoped to the badge row: the page-kind filter <select> also lists every
    // type label as an <option>.
    const affects = (await screen.findByText('Affects')).parentElement!;
    expect(within(affects).getByText('Product')).toBeInTheDocument();
    expect(within(affects).getByText('Category')).toBeInTheDocument();
  });

  it('omits the page-type row for an issue with no classified pages', async () => {
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/issues`, () =>
        HttpResponse.json({ items: [issue({ page_kinds: [] })], next_cursor: null, summary }),
      ),
    );

    renderWithProviders(<IssuesCatalog crawlId={CRAWL} />);

    expect(await screen.findAllByText('WebSite schema is missing')).not.toHaveLength(0);
    expect(screen.queryByText('Affects')).not.toBeInTheDocument();
  });
});
