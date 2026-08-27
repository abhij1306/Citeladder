'use client';

import { useMemo } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  CsvImportDialogShell,
  CsvImportFileInput,
  CsvImportPreview,
  useCsvImportFile,
} from '@/components/ui/csv-import';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import type { PromptInput } from '@/lib/api/prompts';
import { parsePromptCsv, validRows, type ParsedCsv } from '@/lib/prompts/csv';
import { intentLabels } from '@/lib/prompts/forms';

/**
 * CSV import dialog (F7). The file is parsed + validated in the browser and the
 * parsed rows are previewed (with per-row warnings/errors) BEFORE anything is
 * persisted. On confirm, only the importable rows are handed to `onImport`,
 * which posts them to the B3 `/prompt-sets/{id}/import` endpoint.
 */
export function CsvImportDialog({
  open,
  onOpenChange,
  onImport,
  isImporting,
  error,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImport: (rows: PromptInput[]) => Promise<void> | void;
  isImporting?: boolean;
  error?: string;
}>) {
  const { fileName, inputRef, parsed, reset, selectFile } =
    useCsvImportFile<ParsedCsv>(parsePromptCsv);

  const importable = useMemo(() => (parsed ? validRows(parsed) : []), [parsed]);
  const errorCount = parsed ? parsed.rows.filter((row) => row.errors.length > 0).length : 0;

  const handleOpenChange = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const confirm = async () => {
    if (importable.length === 0) return;
    await onImport(importable);
  };

  return (
    <CsvImportDialogShell
      open={open}
      onOpenChange={handleOpenChange}
      title="Import prompts from CSV"
      description="Columns: text, theme, intent, cohort, enabled (header row optional)."
      className="w-205"
      footer={
        <>
          <Button variant="ghost" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={confirm}
            disabled={isImporting || importable.length === 0}
          >
            {isImporting
              ? 'Importing…'
              : `Import ${importable.length} prompt${importable.length === 1 ? '' : 's'}`}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}

        <CsvImportFileInput inputRef={inputRef} onSelect={(file) => void selectFile(file)} />

        {parsed && parsed.errors.length > 0 ? (
          <Alert tone="danger">{parsed.errors.join(' ')}</Alert>
        ) : null}

        {parsed && parsed.rows.length > 0 ? (
          <CsvImportPreview
            errorCount={errorCount}
            fileName={fileName}
            rowCount={parsed.rows.length}
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Row</TableHead>
                  <TableHead>Text</TableHead>
                  <TableHead>Theme</TableHead>
                  <TableHead>Intent</TableHead>
                  <TableHead>Cohort</TableHead>
                  <TableHead>Enabled</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {parsed.rows.map((row) => {
                  const invalid = row.errors.length > 0;
                  return (
                    <TableRow key={row.line} className={invalid ? 'opacity-60' : undefined}>
                      <TableCell numeric className="text-muted">
                        {row.line}
                      </TableCell>
                      <TableCell className="max-w-70 truncate">
                        {row.input.text || <UnavailableValue state="not_set" />}
                      </TableCell>
                      <TableCell>
                        {row.input.theme || <UnavailableValue state="not_set" />}
                      </TableCell>
                      <TableCell>{intentLabels[row.input.intent]}</TableCell>
                      <TableCell>
                        {row.input.cohort === 'comparison' ? 'Comparison' : 'Core'}
                      </TableCell>
                      <TableCell>{row.input.enabled ? 'Yes' : 'No'}</TableCell>
                      <TableCell>
                        {invalid ? (
                          <span className="text-danger-text text-xs">{row.errors.join(' ')}</span>
                        ) : row.warnings.length > 0 ? (
                          <span className="text-warning-text text-xs">
                            {row.warnings.join(' ')}
                          </span>
                        ) : (
                          <span className="text-success-text text-xs">Ready</span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CsvImportPreview>
        ) : null}
      </div>
    </CsvImportDialogShell>
  );
}
