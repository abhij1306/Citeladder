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
});
