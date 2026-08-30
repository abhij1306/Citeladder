'use client';

import { useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import { Input } from '@/components/ui/input';
import {
  parseCursor,
  parseIssueFilters,
  serializeIssueFilters,
  type IssueFilters,
} from '@/lib/site-health/filters';

export function useIssuesCatalogUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const searchParamString = searchParams.toString();
  const urlParams = useMemo(() => new URLSearchParams(searchParamString), [searchParamString]);
  const filters = useMemo(() => parseIssueFilters(urlParams), [urlParams]);
  const cursor = useMemo(() => parseCursor(urlParams), [urlParams]);

  const navigate = (nextFilters: IssueFilters, nextCursor: string | null) => {
    const nextQuery = serializeIssueFilters(nextFilters, nextCursor, urlParams).toString();
    const href = nextQuery ? `${pathname}?${nextQuery}` : pathname;
    const currentHref = searchParamString ? `${pathname}?${searchParamString}` : pathname;
    if (href !== currentHref) router.push(href, { scroll: false });
  };

  return { cursor, filters, navigate };
}

export function IssueSearch({
  query,
  onApply,
}: Readonly<{ query: string; onApply: (query: string) => void }>) {
  const [draft, setDraft] = useState(query);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onApply(draft);
      }}
    >
      <Input
        type="search"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder="Search issues…"
        aria-label="Search issues"
        className="max-w-xs"
      />
    </form>
  );
}
