import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';
import { OverviewPanel } from './overview-panel';

const PROJECT = '11111111-1111-4111-8111-111111111111';
const CRAWL = '22222222-2222-4222-8222-222222222222';
const SNAPSHOT = '33333333-3333-4333-8333-333333333333';
const SOURCE = '44444444-4444-4444-8444-444444444444';

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('OverviewPanel', () => {
  it('opens persisted Web Fundamentals evidence and discloses browser limits', async () => {
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/site-health/overview`, () =>
        HttpResponse.json({
          project_id: PROJECT,
          crawl_id: CRAWL,
          snapshot_id: SNAPSHOT,
          search_eligibility: 'eligible',
          eligibility_totals: { eligible: 1, blocked: 0, unknown: 0, excluded: 0 },
          eligibility_reasons: [],
          technical_integrity_score: 100,
          technical_integrity_coverage: 1,
          technical_integrity_state: 'measured',
          aeo_readiness_score: 72,
          aeo_measurement_coverage: 0.6,
          aeo_measurement_state: 'limited_evidence',
          crawl_coverage: {
            state: 'partial',
            evidence: {},
            denominator_kind: 'selected_intended_public_urls',
          },
          audited_page_count: 1,
          selected_page_count: 1,
          status_counts: { audited: 1 },
          aeo_dimensions: [],
          top_issues: [],
          web_fundamentals: {
            state: 'limited_evidence',
            areas: [
              {
                key: 'accessibility',
                state: 'measured',
                coverage: 1,
                passed_count: 3,
                missing_count: 1,
                unknown_count: 0,
                unavailable_count: 0,
                unavailable_checks: [],
                top_findings: [
                  {
                    rule_id: 'web.accessibility_image_alt',
                    title: 'Images missing alt attributes',
                    remediation: 'Add alt text to informative images.',
                    affected_pages: 1,
                    source_evaluation_ids: [SOURCE],
                  },
                ],
              },
              {
                key: 'mobile',
                state: 'limited_evidence',
                coverage: 0.25,
                passed_count: 1,
                missing_count: 0,
                unknown_count: 0,
                unavailable_count: 3,
                unavailable_checks: ['mobile_layout', 'touch_targets', 'runtime_overflow'],
                top_findings: [],
              },
            ],
            field_data: {
              state: 'unavailable',
              reason: 'provider_not_configured',
              lcp: null,
              inp: null,
              cls: null,
            },
            source_analysis_ids: [SOURCE],
            source_artifact_ids: [SOURCE],
            source_evaluation_ids: [SOURCE],
            limitations: ['HTTP evidence only; browser layout was not measured.'],
          },
          trend: { state: 'unavailable', reason: 'no_comparable_snapshot' },
          change_summary: { state: 'unavailable', reason: 'no_comparable_snapshot' },
          limitations: ['Audited pages only.'],
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<OverviewPanel projectId={PROJECT} crawlId={CRAWL} />);

    expect(await screen.findByText('Limited evidence')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'View evidence' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Images missing alt attributes');
    expect(screen.getByRole('dialog')).toHaveTextContent('mobile_layout');
    expect(screen.getByRole('dialog')).toHaveTextContent('HTTP evidence only');
  });
});
