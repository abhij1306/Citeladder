import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ContextManifest } from './context-manifest';
import { CoverageMeter, LOW_COVERAGE_THRESHOLD } from './coverage-meter';
import { DecisionPrompt } from './decision-prompt';
import { EditableFact } from './editable-fact';
import { Insight, type InsightModel } from './insight';
import { ProvenanceChip } from './provenance-chip';
import { DERIVED_STATES, StateLabel, stateLabel } from './state-label';

/**
 * Contract tests for the shared intelligence components (§5, §6).
 *
 * These pin the rules the plan states as contracts rather than suggestions:
 * no conclusion without evidence, no renormalized composite, exactly two
 * blocking decisions, and durable corrections. Per §12 they cover null,
 * unavailable, conflicting, partial-coverage, and authorization states —
 * a happy-path-only suite would miss every rule that matters here.
 */

const EVIDENCE = { href: '/site/pages?filter=weak', label: '47 pages · /products/*' };

function insightFixture(overrides: Partial<InsightModel> = {}): InsightModel {
  return {
    id: 'insight-1',
    layer: 'site',
    priority: 'high',
    claim: '47 product pages have weak buying-intent coverage',
    evidence: EVIDENCE,
    whyThisMatters: 'Pack expects purchase questions on product detail roles',
    potentialImpact: 'high',
    ...overrides,
  };
}

describe('StateLabel', () => {
  it('gives every state distinct text, never colour alone', () => {
    const labels = DERIVED_STATES.map((state) => stateLabel(state));

    expect(new Set(labels).size).toBe(DERIVED_STATES.length);
    for (const label of labels) expect(label.trim().length).toBeGreaterThan(0);
  });

  it('distinguishes unavailable, not_applicable and observed zero', () => {
    // These three collapse into one empty chart if a screen is careless. The
    // whole component exists so they cannot.
    expect(stateLabel('unavailable')).not.toBe(stateLabel('not_applicable'));
    expect(stateLabel('unavailable')).not.toBe(stateLabel('observed_zero'));
    expect(stateLabel('not_applicable')).not.toBe(stateLabel('observed_zero'));
  });

  it('renders the state as readable text', () => {
    render(<StateLabel state="conflicting" />);

    expect(screen.getByText('Conflicting')).toBeInTheDocument();
  });
});

describe('Insight', () => {
  it('renders the full anatomy in order', () => {
    render(<Insight insight={insightFixture()} />);

    expect(screen.getByText('High priority')).toBeInTheDocument();
    expect(screen.getByText('Site')).toBeInTheDocument();
    expect(
      screen.getByText('47 product pages have weak buying-intent coverage'),
    ).toBeInTheDocument();
    expect(screen.getByText('Evidence')).toBeInTheDocument();
    expect(screen.getByText('Why this matters')).toBeInTheDocument();
    expect(screen.getByText('Potential impact')).toBeInTheDocument();
  });

  it('does not render without resolvable evidence', () => {
    // §5: an insight with no resolvable evidence does not render. Degrading to
    // a plain-text card would be exactly the unevidenced conclusion the
    // product exists to prevent.
    const { container } = render(<Insight insight={insightFixture({ evidence: null })} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('keeps the same server id across layers so caches agree', () => {
    const { container } = render(
      <Insight insight={insightFixture({ layer: 'demand', id: 'shared-7' })} />,
    );

    expect(container.querySelector('[data-insight-id="shared-7"]')).not.toBeNull();
    expect(container.querySelector('[data-layer="demand"]')).not.toBeNull();
  });

  it('opens its evidence', () => {
    render(<Insight insight={insightFixture()} />);

    expect(screen.getByRole('link', { name: /47 pages/ })).toHaveAttribute(
      'href',
      '/site/pages?filter=weak',
    );
  });
});

describe('CoverageMeter', () => {
  it('renders the score over the full denominator with coverage beside it', () => {
    render(<CoverageMeter label="Site health" score={0.62} observed={8} total={10} />);

    expect(screen.getByText('62%')).toBeInTheDocument();
    expect(screen.getByText('8 of 10 measured')).toBeInTheDocument();
  });

  it('never renormalizes a partial composite', () => {
    // 5 of 10 dimensions observed, scoring 0.4 over the FULL denominator.
    // Renormalizing would show 80% — flattering exactly the site that is
    // missing the dimensions it would have failed.
    render(<CoverageMeter label="Site health" score={0.4} observed={5} total={10} />);

    expect(screen.getByText('40%')).toBeInTheDocument();
    expect(screen.queryByText('80%')).toBeNull();
  });

  it('surfaces low coverage as a finding, not a footnote', () => {
    render(<CoverageMeter label="Site health" score={0.4} observed={3} total={10} />);

    expect(screen.getByText(/Low coverage/)).toBeInTheDocument();
  });

  it('stays quiet when coverage is adequate', () => {
    const observed = Math.ceil(LOW_COVERAGE_THRESHOLD * 10) + 1;
    render(<CoverageMeter label="Site health" score={0.9} observed={observed} total={10} />);

    expect(screen.queryByText(/Low coverage/)).toBeNull();
  });

  it('reports an unmeasurable composite as unavailable, not zero', () => {
    render(<CoverageMeter label="Site health" score={0} observed={0} total={0} />);

    expect(screen.getByText('Unavailable')).toBeInTheDocument();
    expect(screen.queryByText('0%')).toBeNull();
  });
});

describe('EditableFact', () => {
  it('shows the derived value when no correction exists', () => {
    render(
      <EditableFact label="Founded" derivedValue="2019" onCorrect={vi.fn()} onWithdraw={vi.fn()} />,
    );

    expect(screen.getByText('2019')).toBeInTheDocument();
    expect(screen.queryByText('Corrected')).toBeNull();
  });

  it('shows the correction, its author, and the derived value it overrides', () => {
    render(
      <EditableFact
        label="Founded"
        derivedValue="2019"
        correction={{ value: '2017', author: 'Dana', correctedAt: '2 Jun' }}
        onCorrect={vi.fn()}
        onWithdraw={vi.fn()}
      />,
    );

    expect(screen.getByText('2017')).toBeInTheDocument();
    expect(screen.getByText('Corrected')).toBeInTheDocument();
    // Attribution and the original derived value both survive the correction.
    expect(screen.getByText(/Dana/)).toBeInTheDocument();
    expect(screen.getByText(/derived value was 2019/)).toBeInTheDocument();
  });

  it('records a correction', () => {
    const onCorrect = vi.fn();
    render(
      <EditableFact
        label="Founded"
        derivedValue="2019"
        onCorrect={onCorrect}
        onWithdraw={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Correct Founded' }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '2017' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction to Founded' }));

    expect(onCorrect).toHaveBeenCalledWith('2017');
  });

  it('treats an unchanged edit as no correction at all', () => {
    const onCorrect = vi.fn();
    const onWithdraw = vi.fn();
    render(
      <EditableFact
        label="Founded"
        derivedValue="2019"
        onCorrect={onCorrect}
        onWithdraw={onWithdraw}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Correct Founded' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save correction to Founded' }));

    // Nothing to correct and nothing to withdraw.
    expect(onCorrect).not.toHaveBeenCalled();
    expect(onWithdraw).not.toHaveBeenCalled();
  });

  it('withdraws when an active correction is cleared', () => {
    // Clearing the field is a withdrawal, not a correction to "". Previously
    // this closed the editor and silently kept the correction.
    const onWithdraw = vi.fn();
    render(
      <EditableFact
        label="Founded"
        derivedValue="2019"
        correction={{ value: '2017', author: 'Dana', correctedAt: '2 Jun' }}
        onCorrect={vi.fn()}
        onWithdraw={onWithdraw}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Correct Founded' }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction to Founded' }));

    expect(onWithdraw).toHaveBeenCalled();
  });

  it('withdraws when an active correction is retyped as the derived value', () => {
    const onWithdraw = vi.fn();
    const onCorrect = vi.fn();
    render(
      <EditableFact
        label="Founded"
        derivedValue="2019"
        correction={{ value: '2017', author: 'Dana', correctedAt: '2 Jun' }}
        onCorrect={onCorrect}
        onWithdraw={onWithdraw}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Correct Founded' }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '2019' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction to Founded' }));

    expect(onWithdraw).toHaveBeenCalled();
    expect(onCorrect).not.toHaveBeenCalled();
  });

  it('keeps the editor open across the save so a rejection keeps the draft', () => {
    // The caller reports the in-flight save via `disabled`. Closing on submit
    // would discard the typed draft if the save were then rejected, because
    // the draft is only re-seeded from the (stale) displayed value.
    const onCorrect = vi.fn();
    const { rerender } = render(
      <EditableFact
        label="Founded"
        derivedValue="2019"
        onCorrect={onCorrect}
        onWithdraw={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Correct Founded' }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '2017' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction to Founded' }));
    expect(onCorrect).toHaveBeenCalledTimes(1);

    // Save in flight: the editor is still open, holding the draft.
    rerender(
      <EditableFact
        label="Founded"
        derivedValue="2019"
        disabled
        onCorrect={onCorrect}
        onWithdraw={vi.fn()}
      />,
    );
    const input = screen.getByRole('textbox');
    expect(input).toHaveValue('2017');

    // A second Enter during the request must not fire a second mutation.
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onCorrect).toHaveBeenCalledTimes(1);
  });

  it('closes the editor once the correction lands', () => {
    const { rerender } = render(
      <EditableFact label="Founded" derivedValue="2019" onCorrect={vi.fn()} onWithdraw={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Correct Founded' }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '2017' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction to Founded' }));

    rerender(
      <EditableFact
        label="Founded"
        derivedValue="2019"
        correction={{ value: '2017', author: 'Dana', correctedAt: '2 Jun' }}
        onCorrect={vi.fn()}
        onWithdraw={vi.fn()}
      />,
    );

    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.getByText('Corrected')).toBeInTheDocument();
  });

  it('stays closed when the correction is withdrawn after landing', () => {
    // Withdrawing clears the submitted value too. Without that, `correction`
    // going away is indistinguishable from a save that never landed, and the
    // editor reopens holding the value the user just withdrew.
    const onWithdraw = vi.fn();
    const correction = { value: '2017', author: 'Dana', correctedAt: '2 Jun' };
    const { rerender } = render(
      <EditableFact label="Founded" derivedValue="2019" onCorrect={vi.fn()} onWithdraw={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Correct Founded' }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '2017' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction to Founded' }));

    rerender(
      <EditableFact
        label="Founded"
        derivedValue="2019"
        correction={correction}
        onCorrect={vi.fn()}
        onWithdraw={onWithdraw}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Withdraw correction to Founded' }));
    expect(onWithdraw).toHaveBeenCalled();

    // The caller drops the correction; the editor must not spring back open.
    rerender(
      <EditableFact
        label="Founded"
        derivedValue="2019"
        correction={null}
        onCorrect={vi.fn()}
        onWithdraw={onWithdraw}
      />,
    );

    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.getByText('2019')).toBeInTheDocument();
  });

  it('withdraws a correction to restore the derived value', () => {
    const onWithdraw = vi.fn();
    render(
      <EditableFact
        label="Founded"
        derivedValue="2019"
        correction={{ value: '2017', author: 'Dana', correctedAt: '2 Jun' }}
        onCorrect={vi.fn()}
        onWithdraw={onWithdraw}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Withdraw correction to Founded' }));

    expect(onWithdraw).toHaveBeenCalled();
  });

  it('offers no correction affordance without authorization', () => {
    render(
      <EditableFact
        label="Founded"
        derivedValue="2019"
        disabled
        onCorrect={vi.fn()}
        onWithdraw={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: 'Correct Founded' })).toBeDisabled();
  });

  it('has no approve affordance', () => {
    // There is no surface for blessing facts that are already right. If an
    // "Approve" control ever appears here, the old model has come back.
    render(
      <EditableFact label="Founded" derivedValue="2019" onCorrect={vi.fn()} onWithdraw={vi.fn()} />,
    );

    expect(screen.queryByRole('button', { name: /approve/i })).toBeNull();
  });
});

describe('DecisionPrompt', () => {
  it('states what will be spent or written', () => {
    render(
      <DecisionPrompt
        kind="run-audit"
        open
        onOpenChange={vi.fn()}
        onConfirm={vi.fn()}
        consequence="Runs 12 prompts across 3 engines on your OpenAI key."
      />,
    );

    expect(
      screen.getByText('Runs 12 prompts across 3 engines on your OpenAI key.'),
    ).toBeInTheDocument();
  });

  it('confirms when nothing blocks', () => {
    const onConfirm = vi.fn();
    render(
      <DecisionPrompt
        kind="save-content"
        open
        onOpenChange={vi.fn()}
        onConfirm={onConfirm}
        consequence="Writes revision 4 of /pricing."
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(onConfirm).toHaveBeenCalled();
  });

  it('disables save while a blocking flag stands', () => {
    // §7.3: blocking flags disable save at the UI *and* the API.
    render(
      <DecisionPrompt
        kind="save-content"
        open
        onOpenChange={vi.fn()}
        onConfirm={vi.fn()}
        consequence="Writes revision 4 of /pricing."
        blockers={[
          {
            id: 'claim-3',
            message: '"Founded 2017" conflicts with project fact "Founded 2019"',
          },
        ]}
      />,
    );

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByText(/conflicts with project fact/)).toBeInTheDocument();
  });

  it('lists every blocker even when two share the same message', () => {
    // Two rules can flag the same text. Keying the list by message would
    // collide and silently render one row, understating what blocks the save.
    render(
      <DecisionPrompt
        kind="save-content"
        open
        onOpenChange={vi.fn()}
        onConfirm={vi.fn()}
        consequence="Writes revision 4 of /pricing."
        blockers={[
          { id: 'claim-3', message: 'Unsupported claim' },
          { id: 'claim-9', message: 'Unsupported claim' },
        ]}
      />,
    );

    expect(screen.getAllByText('Unsupported claim')).toHaveLength(2);
    expect(screen.getByText('2 issues block this')).toBeInTheDocument();
  });
});

describe('ProvenanceChip', () => {
  it('renders pack id and version together', () => {
    render(<ProvenanceChip provenance={{ packId: 'commerce', packVersion: 'v1.2.0' }} />);

    expect(screen.getByText('commerce v1.2.0')).toBeInTheDocument();
  });

  it('joins only the parts that exist', () => {
    render(
      <ProvenanceChip
        provenance={{ packId: 'education', analyzerVersion: '3', snapshotId: 'run-7' }}
      />,
    );

    expect(screen.getByText('education · analyzer 3 · snapshot run-7')).toBeInTheDocument();
  });

  it('omits a version with no pack to attach it to', () => {
    // A bare version identifies nothing, so it is dropped rather than shown
    // as provenance the projection does not actually have.
    render(<ProvenanceChip provenance={{ packVersion: 'v1.2.0', snapshotId: 'run-7' }} />);

    expect(screen.queryByText(/v1\.2\.0/)).toBeNull();
    expect(screen.getByText('snapshot run-7')).toBeInTheDocument();
  });

  it('renders nothing when there is no provenance at all', () => {
    // An empty chip would assert provenance the projection does not have.
    const { container } = render(<ProvenanceChip provenance={{}} />);

    expect(container).toBeEmptyDOMElement();
  });
});

describe('ContextManifest', () => {
  it('reports omitted artifacts, not just included ones', () => {
    render(
      <ContextManifest
        manifest={{
          included: [{ id: 'a', label: 'Home page crawl' }],
          omitted: [{ id: 'b', label: 'Legacy blog', reason: 'Excluded from analyzed scope' }],
        }}
      />,
    );

    expect(screen.getByText('Included · 1')).toBeInTheDocument();
    expect(screen.getByText('Omitted · 1')).toBeInTheDocument();
    expect(screen.getByText('Excluded from analyzed scope')).toBeInTheDocument();
  });

  it('distinguishes truncation from omission', () => {
    render(
      <ContextManifest
        manifest={{
          included: [{ id: 'a', label: 'Home page crawl' }],
          omitted: [],
          truncated: [{ id: 'c', label: 'Product catalog (first 200 rows)' }],
          contradictions: [{ id: 'd', label: 'Founded date disputed' }],
        }}
      />,
    );

    expect(screen.getByText('Truncated · 1')).toBeInTheDocument();
    expect(screen.getByText('Contradictions carried in · 1')).toBeInTheDocument();
  });

  it('renders an empty context honestly', () => {
    render(<ContextManifest manifest={{ included: [], omitted: [] }} />);

    expect(
      screen.getByText("No artifacts were included in this task's context."),
    ).toBeInTheDocument();
  });
});
