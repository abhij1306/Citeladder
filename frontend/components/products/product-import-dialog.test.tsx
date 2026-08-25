/**
 * Product import dialog (D1/COM-4): the browser still previews the CSV, but
 * after a successful import the dialog stays open on the SERVER-side outcome
 * — created/skipped counts plus one row per skipped source row (number,
 * field, reason) — so a silently dropped row is impossible.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ProductImportSummary } from '@/lib/api/types';

import { ProductImportDialog } from './product-import-dialog';

function renderDialog(props: Record<string, unknown> = {}) {
  return render(
    <ProductImportDialog
      open
      onOpenChange={vi.fn()}
      onImport={vi.fn()}
      isImporting={false}
      {...props}
    />,
  );
}

describe('ProductImportDialog file flow', () => {
  it('previews a parsed CSV and hands only the importable rows to onImport', async () => {
    const user = userEvent.setup();
    const onImport = vi.fn();
    renderDialog({ onImport });

    // The picker renders before any result; import stays disabled with 0 rows.
    expect(screen.getByText('Import products from CSV')).toBeInTheDocument();
    expect(
      screen.getByText(/Import one company's catalog only; competitor alternatives/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import 0 products' })).toBeDisabled();

    const file = new File(
      ['name,sku,price,currency\nAcme VoltBike 500,VB-500,"$2,499.00",USD\n,\n'],
      'products.csv',
      { type: 'text/csv' },
    );
    fireEvent.change(screen.getByLabelText('CSV file'), { target: { files: [file] } });

    // Preview: the valid row renders Ready; the sku-less row is named/skipped.
    expect(await screen.findByText('Acme VoltBike 500')).toBeInTheDocument();
    expect(screen.getByText('Ready')).toBeInTheDocument();
    const importButton = screen.getByRole('button', { name: 'Import 1 product' });
    expect(importButton).toBeEnabled();

    await user.click(importButton);
    expect(onImport).toHaveBeenCalledTimes(1);
    expect(onImport).toHaveBeenCalledWith([
      expect.objectContaining({ name: 'Acme VoltBike 500', sku: 'VB-500', price: 2499 }),
    ]);
  });
});

describe('ProductImportDialog result summary (D1)', () => {
  const summary: ProductImportSummary = {
    created: 2,
    updated: 0,
    skipped: 1,
    errors: [
      {
        row: 3,
        field: 'sku',
        message: "Duplicate sku 'VC-500' in this import — the first occurrence was kept",
      },
    ],
  };

  it('renders the counts and one row per skipped source row', async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    renderDialog({ result: summary, onOpenChange });

    expect(screen.getByText('Import complete')).toBeInTheDocument();
    expect(screen.getByText('2 created')).toBeInTheDocument();
    expect(screen.getByText('1 skipped')).toBeInTheDocument();
    expect(screen.getByText(/1 row was skipped/)).toBeInTheDocument();
    expect(
      screen.getByText(/Fix them in the file and import again — already-imported SKUs/),
    ).toBeInTheDocument();
    // Per-row detail: number, field, verbatim server reason.
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('sku')).toBeInTheDocument();
    expect(
      screen.getByText("Duplicate sku 'VC-500' in this import — the first occurrence was kept"),
    ).toBeInTheDocument();
    // The picker is gone on the result view.
    expect(screen.queryByLabelText('CSV file')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Done' }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('shows the all-imported success state when no rows were skipped', () => {
    renderDialog({ result: { created: 3, updated: 0, skipped: 0, errors: [] } });

    expect(screen.getByText('3 created')).toBeInTheDocument();
    expect(screen.getByText('0 skipped')).toBeInTheDocument();
    expect(screen.getByText('Every row imported — no rows were skipped.')).toBeInTheDocument();
    expect(screen.queryByText('Reason')).not.toBeInTheDocument();
  });
});
