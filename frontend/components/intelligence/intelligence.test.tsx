import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Insight, type InsightModel } from './insight';
import { ProvenanceChip } from './provenance-chip';

const EVIDENCE = { href: '/site-health/issues?filter=weak', label: '47 product pages' };

function insightFixture(overrides: Partial<InsightModel> = {}): InsightModel {
  return {
    id: 'insight-1',
    layer: 'site',
    priority: 'high',
    claim: '47 product pages have weak buying-intent coverage',
    evidence: EVIDENCE,
    whyThisMatters: 'Visitors cannot find purchase answers',
    potentialImpact: 'high',
    ...overrides,
  };
}

describe('Insight', () => {
  it('renders only evidence-backed insight anatomy', () => {
    const { rerender, container } = render(<Insight insight={insightFixture()} />);
    expect(
      screen.getByText('47 product pages have weak buying-intent coverage'),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '47 product pages' })).toHaveAttribute(
      'href',
      '/site-health/issues?filter=weak',
    );

    rerender(<Insight insight={insightFixture({ evidence: null })} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('ProvenanceChip', () => {
  it('renders the retained analyzer and snapshot provenance', () => {
    render(<ProvenanceChip provenance={{ analyzerVersion: '3', snapshotId: 'run-7' }} />);
    expect(screen.getByText('analyzer 3 · snapshot run-7')).toBeInTheDocument();
  });

  it('renders nothing when provenance is empty', () => {
    const { container } = render(<ProvenanceChip provenance={{}} />);
    expect(container).toBeEmptyDOMElement();
  });
});
