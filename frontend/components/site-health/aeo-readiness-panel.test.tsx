import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';
import { AeoReadinessPanel } from './aeo-readiness-panel';

const PROJECT = '11111111-1111-4111-8111-111111111111';
const CRAWL = '22222222-2222-4222-8222-222222222222';
const ANALYSIS = '33333333-3333-4333-8333-333333333333';
const SITE_URL = '44444444-4444-4444-8444-444444444444';
const DIMENSIONS = [
  ['answerability', 'Answerability'],
  ['structure', 'Structure'],
  ['evidence', 'Evidence'],
  ['machine-readability', 'Machine-readability'],
  ['authority', 'Authority'],
  ['freshness', 'Freshness'],
  ['crawlability', 'Crawlability'],
] as const;
const RULE_COUNTS = [4, 5, 1, 3, 2, 1, 4] as const;

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

function stubReadiness() {
  mswServer.use(
    http.get(`/api/v1/projects/${PROJECT}/site-health/aeo-readiness`, () =>
      HttpResponse.json({
        state: 'available',
        crawl_id: CRAWL,
        taxonomy_version: 'aeo-readiness-v1',
        analyzer_version: 'page-v1',
        source_analysis_ids: [ANALYSIS],
        analysis_count: 1,
        observed_evaluation_count: 20,
        expected_evaluation_count: 20,
        coverage: 1,
        dimensions: DIMENSIONS.map(([key, label], index) => ({
          key,
          label,
          rule_ids: Array.from({ length: RULE_COUNTS[index] }, (_, ruleIndex) =>
            index === 0 && ruleIndex === 0 ? 'aeo.answer_first' : `rule.${key}.${ruleIndex}`,
          ),
          pass_count: RULE_COUNTS[index] - (index === 0 ? 1 : 0) - (index === 1 ? 1 : 0),
          fail_count: index === 0 ? 1 : 0,
          not_applicable_count: index === 1 ? 1 : 0,
          error_count: 0,
          observed_evaluation_count: RULE_COUNTS[index],
          expected_evaluation_count: RULE_COUNTS[index],
          coverage: 1,
          evidence_links: [
            {
              evaluation_id: `55555555-5555-4555-8555-55555555555${index}`,
              analysis_id: ANALYSIS,
              site_url_id: SITE_URL,
              normalized_url: 'https://acme.test/case-study',
              rule_id: index === 0 ? 'aeo.answer_first' : `rule.${key}.0`,
              outcome: index === 0 ? 'fail' : index === 1 ? 'not_applicable' : 'pass',
            },
          ],
        })),
        limitations: [],
      }),
    ),
  );
}

describe('AEO Readiness', () => {
  it('renders exactly seven dimensions with pass, fail, not-applicable, coverage, and evidence', async () => {
    stubReadiness();
    renderWithProviders(<AeoReadinessPanel projectId={PROJECT} crawlId={CRAWL} />);

    const table = await screen.findByRole('table');
    for (const [, label] of DIMENSIONS) expect(table).toHaveTextContent(label);
    expect(screen.getByText(/persisted rule outcomes—not a new score/i)).toBeInTheDocument();
    expect(table).toHaveTextContent('Not applicable');
    expect(table).toHaveTextContent('100%');

    await userEvent.click(screen.getAllByText(/View 1 evidence link/i)[0]);
    expect(screen.getByText('aeo.answer_first')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'acme.test/case-study' })[0]).toHaveAttribute(
      'href',
      `/site/crawls/${CRAWL}/pages/${SITE_URL}`,
    );
  });
});
