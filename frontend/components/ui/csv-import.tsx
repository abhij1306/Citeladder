'use client';

import { useRef, useState, type ComponentProps, type ReactNode, type RefObject } from 'react';

import { Badge } from '@/components/ui/badge';
import { Dialog } from '@/components/ui/dialog';
import { readCsvFileText } from '@/lib/csv/read-file-text';

/** Shared file-selection lifecycle; parsing remains owned by the importing feature. */
export function useCsvImportFile<T>(parse: (text: string) => T) {
  const [parsed, setParsed] = useState<T | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setParsed(null);
    setFileName(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  const selectFile = async (file: File | undefined) => {
    if (!file) return;
    setFileName(file.name);
    setParsed(parse(await readCsvFileText(file)));
  };

  return { fileName, inputRef, parsed, reset, selectFile };
}

/** Dialog framing shared by browser-side CSV import workflows. */
export function CsvImportDialogShell({
  children,
  ...props
}: Readonly<ComponentProps<typeof Dialog>>) {
  return <Dialog {...props}>{children}</Dialog>;
}

/** The consistent CSV picker; feature-owned parsers receive the selected File. */
export function CsvImportFileInput({
  inputRef,
  onSelect,
}: Readonly<{
  inputRef: RefObject<HTMLInputElement | null>;
  onSelect: (file: File | undefined) => void;
}>) {
  return (
    <label className="grid gap-1.5">
      <span className="text-secondary text-xs font-medium">CSV file</span>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        aria-label="CSV file"
        onChange={(event) => onSelect(event.target.files?.[0])}
        className="focus-ring border-border bg-well text-foreground file:bg-background-alt file:text-foreground block w-full rounded-sm border px-2 py-1.5 text-sm file:me-2 file:rounded-xs file:border-0 file:px-2 file:py-1 file:text-sm"
      />
    </label>
  );
}

/** Parsed-row summary and scrolling frame around a feature-owned table preview. */
export function CsvImportPreview({
  children,
  errorCount,
  fileName,
  rowCount,
}: Readonly<{
  children: ReactNode;
  errorCount: number;
  fileName: string | null;
  rowCount: number;
}>) {
  return (
    <div className="grid gap-2">
      <div className="text-secondary flex items-center gap-3 text-sm">
        <span>
          Parsed <strong className="text-foreground">{rowCount}</strong> row
          {rowCount === 1 ? '' : 's'}
          {fileName ? ` from ${fileName}` : ''}.
        </span>
        {errorCount > 0 ? (
          <Badge variant="status" value="danger">
            {errorCount} skipped
          </Badge>
        ) : null}
      </div>
      <div className="border-border-subtle max-h-85 overflow-auto rounded-sm border">
        {children}
      </div>
    </div>
  );
}
