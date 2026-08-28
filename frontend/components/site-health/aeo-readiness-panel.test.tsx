import { http, HttpResponse } from 'msw';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';
import { AeoReadinessPanel } from './aeo-readiness-panel';

const PROJECT = '11111111-1111-4111-8111-111111111111';
const CRAWL = '22222222-2222-4222-8222-222222222222';
const ANALYSIS = '33333333-3333-4333-8333-333333333333';
const PAGE_A = '44444444-4444-4444-8444-444444444444';
const PAGE_B = '55555555-5555-4555-8555-555555555555';

const DIMENSIONS = [
  ['answerability', 'Answerability'],
  ['structure', 'Structure'],
  ['evidence', 'Evidence'],
  ['machine-readability', 'Machine readability'],
  ['authority', 'Authority'],
  ['freshness', 'Freshness'],
  ['crawlability', 'Crawlability'],
] as const;

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

function dimension(key: string, label: string, failing: boolean) {
  return {
    key,
    label,
    description: `What ${label.toLowerCase()} means in one sentence.`,
    rule_ids: [`rule.${key}.0`],
    pass_count: failing ? 3 : 4,
    fail_count: failing ? 2 : 0,
    not_applicable_count: 1,
    error_count: 0,
    observed_evaluation_count: failing ? 6 : 5,
    expected_evaluation_count: 6,
    coverage: 1,
    checked_page_count: 5,
    failing_page_count: failing ? 2 : 0,
    checks: [
      {
        rule_id: `rule.${key}.0`,
        title: failing ? 'Answer is not stated first' : 'Headings are unique',
        remediation: 'Move the direct answer into the first paragraph.',
        pass_count: failing ? 3 : 4,
        fail_count: failing ? 2 : 0,
        not_applicable_count: 1,
        failing_page_count: failing ? 2 : 0,
      },
    ],
    evidence_pages: failing
      ? [
          {
            site_url_id: PAGE_A,
            normalized_url: 'https://acme.test/blogs/american-summer',
            failed_checks: [
              { rule_id: `rule.${key}.0`, title: 'Answer is not stated first' },
              { rule_id: `rule.${key}.1`, title: 'No question headings' },
            ],
          },
          {
            site_url_id: PAGE_B,
            normalized_url: 'https://acme.test/blogs/rooted-in-fall',
            failed_checks: [{ rule_id: `rule.${key}.0`, title: 'Answer is not stated first' }],
          },
        ]
      : [],
    evidence_truncated: false,
  };
}

function stubReadiness(overrides: Record<string, unknown> = {}) {
  mswServer.use(
    http.get(`/api/v1/projects/${PROJECT}/site-health/aeo-readiness`, () =>
      HttpResponse.json({
        state: 'available',
        crawl_id: CRAWL,
        taxonomy_version: 'aeo-readiness-v1',
        analyzer_version: 'page-v1',
        source_analysis_ids: [ANALYSIS],
        analysis_count: 5,
        observed_evaluation_count: 40,
        expected_evaluation_count: 42,
        coverage: 0.95,
        dimensions: DIMENSIONS.map(([key, label], index) => dimension(key, label, index === 0)),
        limitations: [],
        ...overrides,
      }),
    ),
  );
}

describe('AEO Readiness', () => {
  it('renders all seven dimensions with a plain-language description', async () => {
    stubReadiness();
    renderWithProviders(<AeoReadinessPanel projectId={PROJECT} crawlId={CRAWL} />);

    await screen.findByText('AEO Readiness');
    for (const [, label] of DIMENSIONS) expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText(/what answerability means in one sentence/i)).toBeInTheDocument();
    // The header names what needs work instead of leaving the reader to scan.
    expect(screen.getByText(/1 of 7 need work: Answerability/)).toBeInTheDocument();
  });

  it('counts pages that need work, never a bare evaluation total', async () => {
    stubReadiness();
    renderWithProviders(<AeoReadinessPanel projectId={PROJECT} crawlId={CRAWL} />);

    expect(await screen.findByText('2 of 5 checked pages need work')).toBeInTheDocument();
    expect(screen.getAllByText('All 5 checked pages pass')).toHaveLength(6);
    // The old surface claimed "25 evidence links" on every dimension.
    expect(screen.queryByText(/evidence link/i)).toBeNull();
  });

  it('names checks by their catalog title and never by a rule id', async () => {
    stubReadiness();
    renderWithProviders(<AeoReadinessPanel projectId={PROJECT} crawlId={CRAWL} />);

    expect(await screen.findByText('Answer is not stated first')).toBeInTheDocument();
    expect(screen.queryByText(/rule\.answerability\.0/)).toBeNull();
    expect(screen.queryByText(/^aeo\./)).toBeNull();
  });

  it('reveals the remediation for a check on demand', async () => {
    stubReadiness();
    renderWithProviders(<AeoReadinessPanel projectId={PROJECT} crawlId={CRAWL} />);

    await userEvent.click(
      await screen.findByRole('button', { name: /Answer is not stated first/ }),
    );
    expect(
      screen.getByText('Move the direct answer into the first paragraph.'),
    ).toBeInTheDocument();
  });

  it('lists each failing page once with the checks it failed', async () => {
    stubReadiness();
    renderWithProviders(<AeoReadinessPanel projectId={PROJECT} crawlId={CRAWL} />);

    await userEvent.click(await screen.findByRole('button', { name: 'View 2 pages to fix' }));
    const link = screen.getByRole('link', { name: 'acme.test/blogs/american-summer' });
    expect(link).toHaveAttribute('href', `/site/crawls/${CRAWL}/pages/${PAGE_A}`);
    // One row per page — the old drawer repeated the URL once per rule.
    expect(screen.getAllByRole('link', { name: 'acme.test/blogs/american-summer' })).toHaveLength(
      1,
    );
    const row = link.closest('li');
    expect(within(row!).getByText('No question headings')).toBeInTheDocument();
    // Raw outcome tokens are gone.
    expect(screen.queryByText('fail')).toBeNull();
  });

  it('says a bounded evidence list is bounded rather than implying it is the total', async () => {
    stubReadiness({
      dimensions: DIMENSIONS.map(([key, label], index) => {
        const base = dimension(key, label, index === 0);
        return index === 0 ? { ...base, failing_page_count: 140, evidence_truncated: true } : base;
      }),
    });
    renderWithProviders(<AeoReadinessPanel projectId={PROJECT} crawlId={CRAWL} />);

    await userEvent.click(await screen.findByRole('button', { name: 'View 140 pages to fix' }));
    expect(screen.getByText(/Showing the 2 most affected of 140 pages/)).toBeInTheDocument();
  });

  it('shows the persisted empty state rather than an empty grid', async () => {
    stubReadiness({ state: 'unavailable', limitations: ['Run a crawl first.'] });
    renderWithProviders(<AeoReadinessPanel projectId={PROJECT} crawlId={CRAWL} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Run a crawl first.');
  });
});
