import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/render';

import { BulkActions } from './commerce-workspace';

describe('BulkActions', () => {
  it('keeps a stable disabled action area before targets are selected', () => {
    renderWithProviders(
      <BulkActions
        count={0}
        hasCheckedKeys={false}
        pending={false}
        onDiscover={vi.fn()}
        onClear={vi.fn()}
      />,
    );

    expect(screen.getByText('No targets selected')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Find competitors' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Clear selection' })).toBeDisabled();
  });

  it('enables bulk actions and reports the checked target count', () => {
    const onDiscover = vi.fn();
    const onClear = vi.fn();
    renderWithProviders(
      <BulkActions
        count={2}
        hasCheckedKeys
        pending={false}
        onDiscover={onDiscover}
        onClear={onClear}
      />,
    );

    expect(screen.getByText('2 targets selected')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Find competitors' }));
    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }));
    expect(onDiscover).toHaveBeenCalledOnce();
    expect(onClear).toHaveBeenCalledOnce();
  });

  it('allows stale checked keys to be cleared when no catalog targets match', () => {
    const onClear = vi.fn();
    renderWithProviders(
      <BulkActions
        count={0}
        hasCheckedKeys
        pending={false}
        onDiscover={vi.fn()}
        onClear={onClear}
      />,
    );

    expect(screen.getByRole('button', { name: 'Find competitors' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }));
    expect(onClear).toHaveBeenCalledOnce();
  });
});
