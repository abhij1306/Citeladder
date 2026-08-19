import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { CsvImportDialog } from './csv-import-dialog';

describe('CsvImportDialog file flow', () => {
  it('uses the shared file lifecycle while preserving prompt preview semantics', async () => {
    const user = userEvent.setup();
    const onImport = vi.fn();
    render(<CsvImportDialog open onOpenChange={vi.fn()} onImport={onImport} isImporting={false} />);

    await user.upload(
      screen.getByLabelText('CSV file'),
      new File(['text,theme,intent\nHow do I choose a bike?,Buying,informational'], 'prompts.csv', {
        type: 'text/csv',
      }),
    );

    expect(await screen.findByText('How do I choose a bike?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Import 1 prompt' }));
    expect(onImport).toHaveBeenCalledWith([
      expect.objectContaining({ text: 'How do I choose a bike?', theme: 'Buying' }),
    ]);
  });
});
