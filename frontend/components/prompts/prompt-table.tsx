'use client';

import { Archive, Check, MoreHorizontal, Pencil, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownSeparator,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { TablePagination, useTablePage } from '@/components/ui/table-pagination';
import { Tooltip } from '@/components/ui/tooltip';
import { Switch } from '@/components/ui/switch';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import type { Prompt, PromptStatus } from '@/lib/api/types';
import { buyerStageLabels, intentLabels } from '@/lib/prompts/forms';

/** Rows per page on the prompt table (client-side; the list arrives whole). */
const PAGE_SIZE = 10;

/**
 * Prompt table (F7). Dense analytics table with columns text / theme / stage /
 * intent / enabled and per-row actions (edit, delete, enable/disable toggle,
 * and — when `onSetStatus` is wired — archive or restore transitions).
 * Client-side pagination footer
 * (mono indicator + ghost buttons) per the prompts frame. Purely
 * presentational — CRUD is delegated to callbacks owned by the page.
 */
export function PromptTable({
  prompts,
  onEdit,
  onDelete,
  onToggleEnabled,
  onSetStatus,
  busyId,
}: Readonly<{
  prompts: Prompt[];
  onEdit: (prompt: Prompt) => void;
  onDelete: (prompt: Prompt) => void;
  onToggleEnabled: (prompt: Prompt) => void;
  onSetStatus?: (prompt: Prompt, status: PromptStatus) => void;
  busyId?: string | null;
}>) {
  const { page, setPage, pageCount, from, to } = useTablePage(prompts.length, PAGE_SIZE);
  const pagedPrompts = prompts.slice(from - 1, to);

  return (
    <div className="bg-panel border-border overflow-hidden rounded-[var(--radius-card)] border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Prompt</TableHead>
            <TableHead>Theme</TableHead>
            <TableHead>Stage</TableHead>
            <TableHead>Intent</TableHead>
            <TableHead>Enabled</TableHead>
            <TableHead className="w-16 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {pagedPrompts.map((prompt) => (
            <TableRow key={prompt.id}>
              <TableCell className="max-w-130 min-w-60">
                <Tooltip content={prompt.text}>
                  <span className="text-foreground line-clamp-2 block">{prompt.text}</span>
                </Tooltip>
              </TableCell>
              <TableCell className="max-w-45">
                {prompt.theme ? (
                  <Tooltip content={prompt.theme}>
                    <Badge variant="neutral" className="max-w-full">
                      <span className="min-w-0 truncate">{prompt.theme}</span>
                    </Badge>
                  </Tooltip>
                ) : (
                  <UnavailableValue state="not_set" />
                )}
              </TableCell>
              <TableCell className="text-secondary">
                {prompt.buyer_stage ? (
                  buyerStageLabels[prompt.buyer_stage]
                ) : (
                  <UnavailableValue state="not_set" />
                )}
              </TableCell>
              <TableCell className="text-secondary">{intentLabels[prompt.intent]}</TableCell>
              <TableCell>
                <Switch
                  checked={prompt.enabled}
                  label={`${prompt.enabled ? 'Disable' : 'Enable'} prompt`}
                  disabled={busyId === prompt.id}
                  onCheckedChange={() => onToggleEnabled(prompt)}
                />
              </TableCell>
              <TableCell className="text-right">
                <Dropdown>
                  <DropdownTrigger asChild>
                    <Button variant="ghost" size="icon" aria-label="Prompt actions">
                      <MoreHorizontal className="size-4" aria-hidden />
                    </Button>
                  </DropdownTrigger>
                  <DropdownContent align="end">
                    {onSetStatus && prompt.status === 'archived' ? (
                      <DropdownItem onSelect={() => onSetStatus(prompt, 'active')}>
                        <Check className="size-4" aria-hidden />
                        Restore
                      </DropdownItem>
                    ) : null}
                    <DropdownItem onSelect={() => onEdit(prompt)}>
                      <Pencil className="size-4" aria-hidden />
                      Edit
                    </DropdownItem>
                    {onSetStatus && prompt.status !== 'archived' ? (
                      <DropdownItem onSelect={() => onSetStatus(prompt, 'archived')}>
                        <Archive className="size-4" aria-hidden />
                        Archive
                      </DropdownItem>
                    ) : null}
                    <DropdownSeparator className="bg-border-subtle my-1 h-px" />
                    <DropdownItem
                      onSelect={() => onDelete(prompt)}
                      className="text-danger-text data-[highlighted]:bg-danger-bg"
                    >
                      <Trash2 className="size-4" aria-hidden />
                      Delete
                    </DropdownItem>
                  </DropdownContent>
                </Dropdown>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <TablePagination
        page={page}
        pageCount={pageCount}
        from={from}
        to={to}
        total={prompts.length}
        noun="prompts"
        onPageChange={setPage}
      />
    </div>
  );
}
