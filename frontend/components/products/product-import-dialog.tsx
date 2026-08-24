'use client';

import { useMemo } from 'react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  CsvImportDialogShell,
  CsvImportFileInput,
  CsvImportPreview,
  useCsvImportFile,
} from '@/components/ui/csv-import';
import { MutationNotice } from '@/components/ui/mutation-notice';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { MutationNotice as MutationNoticeData } from '@/lib/api/mutation-notice';
import type { ProductInput } from '@/lib/api/products';
import type { ProductImportSummary } from '@/lib/api/types';
import {
  parseProductCsv,
  validProductRows,
  type ParsedProductCsv,
  type ParsedProductRow,
} from '@/lib/products/csv';

/**
 * Product CSV import dialog (mirrors the prompts CSV import dialog). The file
 * is parsed + validated in the browser and previewed (with per-row
 * warnings/errors) BEFORE anything is persisted. On confirm, only the
 * importable rows are handed to `onImport`, which posts them to the
 * `/projects/{id}/products/import` endpoint. A header row is required —
 * matching the backend. After a successful import the dialog stays open on
 * the server-side outcome (D1): created/skipped counts and the reason every
 * skipped row was dropped, so silent skips are impossible (COM-4).
 */
export function ProductImportDialog({
  open,
  onOpenChange,
  onImport,
  isImporting,
  error,
  onRetry,
  result,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImport: (rows: ProductInput[]) => Promise<void> | void;
  isImporting?: boolean;
  /** The A4 mutation notice for a failed import (verbatim 4xx, transient retry). */
  error?: MutationNoticeData;
  /** Retry affordance for a transient import failure (re-posts the same rows). */
  onRetry?: () => void;
  /** The server-side import summary (D1) — shown after a successful import. */
  result?: ProductImportSummary | null;
}>) {
  const { fileName, inputRef, parsed, reset, selectFile } =
    useCsvImportFile<ParsedProductCsv>(parseProductCsv);

  const importable = useMemo(() => (parsed ? validProductRows(parsed) : []), [parsed]);
  const errorCount = parsed ? parsed.rows.filter((row) => row.errors.length > 0).length : 0;

  const handleOpenChange = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const confirm = async () => {
    if (importable.length === 0) return;
    await onImport(importable);
  };

  if (result) {
    return (
      <CsvImportDialogShell
        open={open}
        onOpenChange={handleOpenChange}
        title="Import complete"
        description="The server-side outcome of the import — every skipped row is named."
        className="w-215"
        footer={
          <Button variant="primary" onClick={() => handleOpenChange(false)}>
            Done
          </Button>
        }
      >
        <ImportResultSummary result={result} />
      </CsvImportDialogShell>
    );
  }

  return (
    <CsvImportDialogShell
      open={open}
      onOpenChange={handleOpenChange}
      title="Import products from CSV"
      description="Columns: name, sku, variant, brand, category, price, currency, url, gtin, mpn, availability, condition, description, aliases (header row required)."
      className="w-215"
      footer={
        <>
          <Button variant="ghost" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => void confirm()}
            disabled={isImporting || importable.length === 0}
          >
            {isImporting
              ? 'Importing…'
              : `Import ${importable.length} product${importable.length === 1 ? '' : 's'}`}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <p className="text-secondary text-sm">
          Need a format?{' '}
          <a className="text-link" href="/samples/commerce-products.csv" download>
            Download the sample CSV
          </a>
          .
        </p>
        {error ? <MutationNotice notice={error} onRetry={onRetry} /> : null}

        <CsvImportFileInput inputRef={inputRef} onSelect={(file) => void selectFile(file)} />

        {parsed && parsed.errors.length > 0 ? (
          <Alert tone="danger">{parsed.errors.join(' ')}</Alert>
        ) : null}

        {parsed && parsed.rows.length > 0 ? (
          <ProductCsvPreview errorCount={errorCount} fileName={fileName} rows={parsed.rows} />
        ) : null}
      </div>
    </CsvImportDialogShell>
  );
}

function ProductCsvPreview({
  errorCount,
  fileName,
  rows,
}: Readonly<{
  errorCount: number;
  fileName: string | null;
  rows: ParsedProductRow[];
}>) {
  return (
    <CsvImportPreview errorCount={errorCount} fileName={fileName} rowCount={rows.length}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Row</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>SKU</TableHead>
            <TableHead>Variant</TableHead>
            <TableHead>Category</TableHead>
            <TableHead>Price</TableHead>
            <TableHead>Currency</TableHead>
            <TableHead>URL</TableHead>
            <TableHead>GTIN</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <ProductCsvPreviewRow key={row.line} row={row} />
          ))}
        </TableBody>
      </Table>
    </CsvImportPreview>
  );
}

function ProductCsvPreviewRow({ row }: Readonly<{ row: ParsedProductRow }>) {
  const attributes = row.input.attributes ?? {};
  const invalid = row.errors.length > 0;
  return (
    <TableRow className={invalid ? 'opacity-60' : undefined}>
      <TableCell numeric className="text-muted">
        {row.line}
      </TableCell>
      <TableCell className="max-w-45 truncate">{row.input.name || '—'}</TableCell>
      <TableCell className="font-mono text-xs">{row.input.sku || '—'}</TableCell>
      <TableCell className="max-w-35 truncate">{row.input.variants?.[0]?.name || '—'}</TableCell>
      <TableCell>{String(attributes.category ?? '') || '—'}</TableCell>
      <ProductPriceCell price={row.input.price} />
      <TableCell>{row.input.currency || '—'}</TableCell>
      <TableCell className="max-w-40 truncate">{row.input.url || '—'}</TableCell>
      <TableCell>{String(attributes.gtin ?? '') || '—'}</TableCell>
      <TableCell>
        <ProductCsvRowStatus row={row} />
      </TableCell>
    </TableRow>
  );
}

function ProductPriceCell({ price }: Readonly<{ price: number | null | undefined }>) {
  return <TableCell numeric>{price ?? '—'}</TableCell>;
}

function ProductCsvRowStatus({ row }: Readonly<{ row: ParsedProductRow }>) {
  if (row.errors.length > 0)
    return <span className="text-danger-text text-xs">{row.errors.join(' ')}</span>;
  if (row.warnings.length > 0)
    return <span className="text-warning-text text-xs">{row.warnings.join(' ')}</span>;
  return <span className="text-success-text text-xs">Ready</span>;
}

/**
 * The server-side import outcome (D1): created/skipped counts as badges
 * (the text carries the meaning, never color-only) plus one row per skipped
 * source row with its number, field, and reason — replacing the old silent
 * 201 (COM-4). `updated` is reserved and always 0 in v1, so it is not shown.
 */
function ImportResultSummary({ result }: Readonly<{ result: ProductImportSummary }>) {
  return (
    <div className="grid gap-4 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="status" value="success">
          {result.created} created
        </Badge>
        {result.skipped > 0 ? (
          <Badge variant="status" value="warning">
            {result.skipped} skipped
          </Badge>
        ) : (
          <Badge variant="status" value="success">
            0 skipped
          </Badge>
        )}
      </div>

      {result.errors.length === 0 ? (
        <Alert tone="success">Every row imported — no rows were skipped.</Alert>
      ) : (
        <div className="grid gap-2">
          <p className="text-secondary text-sm">
            {result.errors.length} row{result.errors.length === 1 ? ' was' : 's were'} skipped. Fix
            them in the file and import again — already-imported SKUs are left unchanged.
          </p>
          <div className="border-border-subtle max-h-75 overflow-auto rounded-sm border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Row</TableHead>
                  <TableHead>Field</TableHead>
                  <TableHead className="min-w-80">Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.errors.map((rowError) => (
                  <TableRow key={`${rowError.row}:${rowError.field}`}>
                    <TableCell numeric className="text-muted">
                      {rowError.row}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{rowError.field || '—'}</TableCell>
                    <TableCell className="text-secondary text-sm">{rowError.message}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </div>
  );
}
