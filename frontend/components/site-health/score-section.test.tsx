import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { SiteHealthDashboard } from '@/lib/api/types';

import { ScoreSection } from './score-section';

describe('ScoreSection', () => {
  it('preserves unavailable measurement states when scores are absent', () => {
    const dashboard = {
      score_summary: {
        technical_integrity_score: null,
        technical_integrity_coverage: 0.5,
        technical_integrity_state: 'limited_evidence',
        aeo_readiness_score: null,
        aeo_measurement_coverage: null,
        aeo_measurement_state: 'excluded',
      },
    } as SiteHealthDashboard;

    render(<ScoreSection crawl={null} dashboard={dashboard} />);

    expect(screen.getAllByText('Limited evidence').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Excluded/).length).toBeGreaterThan(0);
  });

  it('hides readiness ratios but keeps evidence coverage visible when limited', () => {
    const dashboard = {
      score_summary: {
        technical_integrity_score: 73,
        technical_integrity_coverage: 0.6,
        technical_integrity_state: 'limited_evidence',
        aeo_readiness_score: 61,
        aeo_measurement_coverage: 0.7,
        aeo_measurement_state: 'limited_evidence',
      },
    } as SiteHealthDashboard;

    render(<ScoreSection crawl={null} dashboard={dashboard} />);

    expect(screen.queryByText('73 / 100')).not.toBeInTheDocument();
    expect(screen.queryByText('61 / 100')).not.toBeInTheDocument();
    expect(screen.getAllByText('Limited evidence')).toHaveLength(4);
    expect(screen.getByText('70 / 100')).toBeInTheDocument();
  });
});
