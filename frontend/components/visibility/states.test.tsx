import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Visibility } from '@/lib/api/types';
import type { ActiveRun } from '@/lib/visibility/dashboard';

import { ActiveRunBanner } from './active-run-banner';
import { VisibilityEmptyState } from './empty-state';
import { RankingsTable } from './rankings-table';

vi.mock('@/components/runs/launch-audit-button', () => ({
  LaunchAuditButton: ({ children }: { children: React.ReactNode }) => (
    <button type="button">{children}</button>
  ),
}));

/**
 * The three "there is nothing to show yet" surfaces of the Visibility
 * workspace.
 *
 * The distinction that matters: "you have never run an audit" and "your audit
 * is still running" are different situations with different correct actions.
 * Showing the launch CTA to someone whose run is already in flight invites a
 * duplicate, paid run; showing a bare empty state hides the fact that results
 * are on the way.
 */
function visibility(rankings: Visibility['rankings']): Visibility {
  return { rankings } as Visibility;
}

function rankingRow(name: string, shareOfVoice: number | null) {
  return {
    name,
    is_brand: false,
    logo_url: null,
    website_url: null,
    mention_rate: 0.5,
    citation_rate: 0.2,
    share_of_voice: shareOfVoice,
    mention_count: 1,
    sentiment: null,
    avg_position: null,
  };
}

describe('VisibilityEmptyState', () => {
  it('invites a first audit when nothing is running', () => {
    render(<VisibilityEmptyState />);

    expect(screen.getByText('No completed runs yet')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Launch your first audit' })).toBeVisible();
    expect(screen.queryByRole('link', { name: 'View runs' })).not.toBeInTheDocument();
  });

  it('routes to Runs instead of inviting a duplicate when one is already running', () => {
    render(<VisibilityEmptyState hasActiveRun />);

    // Offering "launch" here would invite a second paid run for results that
    // are already on the way.
    expect(screen.queryByRole('button', { name: /Launch/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View runs' })).toHaveAttribute('href', '/runs');
    expect(screen.getByText(/results appear here when it finishes/i)).toBeVisible();
  });
});

describe('ActiveRunBanner', () => {
  const run: ActiveRun = {
    id: '11111111-1111-4111-8111-111111111111',
    status: 'running',
    createdAt: '2026-08-01T00:00:00Z',
  };

  it('names the run’s current status', () => {
    render(<ActiveRunBanner run={run} />);

    expect(screen.getByText(/A run is in progress \(Running\)/)).toBeVisible();
  });

  it('links to that exact run rather than the runs list', () => {
    // An active run has no metric snapshot, so it cannot appear in the run
    // selector; this link is the only way to reach it from here.
    render(<ActiveRunBanner run={run} />);

    expect(screen.getByRole('link', { name: /Watch live progress/ })).toHaveAttribute(
      'href',
      `/runs/${run.id}`,
    );
  });

  it('reflects a different lifecycle status', () => {
    render(<ActiveRunBanner run={{ ...run, status: 'analyzing' }} />);

    expect(screen.getByText(/\(Analyzing\)/)).toBeVisible();
  });
});

describe('RankingsTable', () => {
  it('explains an empty result instead of rendering a headerless table', () => {
    render(<RankingsTable visibility={visibility([])} />);

    expect(screen.getByText(/No brand or competitor mentions were recorded/)).toBeVisible();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('orders rows by share of voice, descending', () => {
    render(
      <RankingsTable
        visibility={visibility([
          rankingRow('Initech', 0.1),
          rankingRow('Acme', 0.6),
          rankingRow('Globex', 0.3),
        ] as Visibility['rankings'])}
      />,
    );

    const names = screen
      .getAllByRole('row')
      .slice(1)
      .map((row) => row.textContent);
    expect(names[0]).toContain('Acme');
    expect(names[1]).toContain('Globex');
    expect(names[2]).toContain('Initech');
  });

  it('breaks a share tie by name so the order is stable between renders', () => {
    render(
      <RankingsTable
        visibility={visibility([
          rankingRow('Zeta', 0.4),
          rankingRow('Alpha', 0.4),
        ] as Visibility['rankings'])}
      />,
    );

    const names = screen
      .getAllByRole('row')
      .slice(1)
      .map((row) => row.textContent);
    expect(names[0]).toContain('Alpha');
    expect(names[1]).toContain('Zeta');
  });

  it('sorts an unknown share as the lowest rather than dropping the row', () => {
    render(
      <RankingsTable
        visibility={visibility([
          rankingRow('Unknown', null),
          rankingRow('Acme', 0.2),
        ] as Visibility['rankings'])}
      />,
    );

    const names = screen
      .getAllByRole('row')
      .slice(1)
      .map((row) => row.textContent);
    // The brand was still mentioned; only its share is unknown, so it belongs
    // in the table rather than being silently omitted.
    expect(names).toHaveLength(2);
    expect(names[0]).toContain('Acme');
    expect(names[1]).toContain('Unknown');
  });
});
