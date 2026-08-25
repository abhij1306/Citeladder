import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { VisibilityExecutionEvidence } from '@/lib/api/types';

import {
  EvidenceEmpty,
  EvidenceError,
  EvidenceFilteredEmpty,
  EvidenceSkeleton,
  ExecutionHeader,
  ProvenanceDisclosure,
  TruncationNotice,
} from './evidence-states';

/**
 * `components/visibility` is the largest untested frontend directory, and Track
 * is the measured product outcome — so its data states are the ones a user
 * reads when the answer is "nothing", "not yet", or "we could not load it".
 *
 * The distinction these lock down is the one an untested surface loses: an
 * EMPTY result ("no executions yet — go run one") and a FILTERED-empty result
 * ("your filters excluded everything") are different facts, and collapsing them
 * tells a user their data does not exist when it does.
 */
const ITEM: VisibilityExecutionEvidence = {
  audit_id: '11111111-1111-4111-8111-111111111111',
  task_id: 'aaaaaaaa-1111-4111-8111-111111111111',
  analysis_id: 'bbbbbbbb-2222-4222-8222-222222222222',
  artifact_id: 'cccccccc-3333-4333-8333-333333333333',
  prompt_snapshot_id: 'dddddddd-4444-4444-8444-444444444444',
  prompt_id: 'eeeeeeee-5555-4555-8555-555555555555',
  prompt_index: 0,
  prompt_text: 'Best trail running shoes',
  repetition: 0,
  completed_at: '2026-08-01T10:30:00Z',
  logical_engine: 'gemini',
  transport_provider: 'google',
  transport_model: 'gemini-2.5-pro',
  retrieval_enabled: true,
  search_used: true,
  search_query_count: 2,
  query_text_available: true,
  state: 'queries_available',
  search_events: [],
  event_source: 'raw_artifact',
  mentions: [],
  citations: [],
};

describe('evidence loading and error states', () => {
  it('hides the skeleton from assistive technology', () => {
    const { container } = render(<EvidenceSkeleton title="Query Fanout" />);

    // A skeleton announced to a screen reader is noise, not content.
    expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });

  it('offers a retry and promises the filters are untouched', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<EvidenceError title="Query Fanout" onRetry={onRetry} />);

    expect(screen.getByText(/Couldn't load this evidence/)).toBeVisible();
    expect(screen.getByText(/Your filters are unchanged/)).toBeVisible();
    await user.click(screen.getByRole('button', { name: /Retry/ }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe('evidence empty states', () => {
  it('sends a user with no executions to Runs', () => {
    render(
      <EvidenceEmpty
        title="Mentions & Citations"
        heading="No evidence yet"
        body="Run a visibility audit to collect evidence."
      />,
    );

    expect(screen.getByText('No evidence yet')).toBeVisible();
    // The fix for "no data" is to run something, so the state has to route
    // there rather than dead-ending.
    expect(screen.getByRole('link', { name: 'View Runs' })).toHaveAttribute('href', '/runs');
  });

  it('says filters are the cause when a filtered result is empty', () => {
    render(<EvidenceFilteredEmpty title="Query Fanout" body="Try widening the date range." />);

    expect(screen.getByText('No results match these filters')).toBeVisible();
    // Crucially NOT the "go run an audit" state: the data may well exist.
    expect(screen.queryByRole('link', { name: 'View Runs' })).not.toBeInTheDocument();
  });

  it('offers a clear-filters escape when the caller can clear them', async () => {
    const user = userEvent.setup();
    const onClear = vi.fn();
    render(
      <EvidenceFilteredEmpty title="Query Fanout" body="Widen the range." onClear={onClear} />,
    );

    await user.click(screen.getByRole('button', { name: 'Clear filters' }));

    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it('omits the clear-filters button when there is nothing to clear', () => {
    render(<EvidenceFilteredEmpty title="Query Fanout" body="Widen the range." />);

    expect(screen.queryByRole('button', { name: 'Clear filters' })).not.toBeInTheDocument();
  });
});

describe('TruncationNotice', () => {
  it('names the bounded window rather than implying a total', () => {
    render(<TruncationNotice limit={100} />);

    // The endpoint returns a newest-first window with no total, so the notice
    // must not suggest one.
    expect(screen.getByText(/Showing newest 100 executions/)).toBeVisible();
  });
});

describe('ExecutionHeader', () => {
  it('labels the engine and names the exact transport model', () => {
    render(<ExecutionHeader item={ITEM} />);

    // Provenance: the answer came from one specific model, not just "Gemini".
    expect(screen.getByText('gemini-2.5-pro')).toBeVisible();
  });

  it('hides the repeat marker for the first execution', () => {
    render(<ExecutionHeader item={{ ...ITEM, repetition: 0 }} />);

    expect(screen.queryByText(/repeat/)).not.toBeInTheDocument();
  });

  it('numbers a repeated execution from one, not zero', () => {
    render(<ExecutionHeader item={{ ...ITEM, repetition: 2 }} />);

    expect(screen.getByText(/repeat 3/)).toBeVisible();
  });

  it('says the date is unavailable rather than rendering an invalid one', () => {
    render(<ExecutionHeader item={{ ...ITEM, completed_at: null }} />);

    expect(screen.getByText(/Date unavailable/)).toBeVisible();
  });

  it('renders caller-supplied trailing content', () => {
    render(<ExecutionHeader item={ITEM} trailing={<span>2 searches</span>} />);

    expect(screen.getByText('2 searches')).toBeVisible();
  });
});

describe('ProvenanceDisclosure', () => {
  it('keeps raw ids collapsed behind a disclosure', () => {
    render(<ProvenanceDisclosure item={ITEM} />);

    // Ids are audit trail, not the evidence a reader came for, so they must
    // not sit on the primary surface.
    const summary = screen.getByText('Provenance');
    expect(summary.closest('details')).not.toHaveAttribute('open');
  });

  it('names the artifact the evidence was read from', () => {
    render(<ProvenanceDisclosure item={ITEM} />);

    // Present in the DOM but collapsed: asserted by content, not visibility.
    const line = screen.getByText(/^Provenance: task/);
    expect(line).toHaveTextContent('task aaaaaaaa');
    expect(line).toHaveTextContent('analysis bbbbbbbb');
    expect(line).toHaveTextContent('artifact cccccccc');
  });

  it('says the artifact was pruned rather than implying no source', () => {
    render(
      <ProvenanceDisclosure item={{ ...ITEM, event_source: 'audit_task', artifact_id: null }} />,
    );

    expect(screen.getByText(/^Provenance: task/)).toHaveTextContent('task (artifact pruned)');
  });

  it('says there was no search source at all when there was none', () => {
    render(<ProvenanceDisclosure item={{ ...ITEM, event_source: 'none', artifact_id: null }} />);

    // "No search source" and "artifact pruned" are different facts about the
    // run and must not read the same.
    expect(screen.getByText(/^Provenance: task/)).toHaveTextContent('no search source');
  });
});
