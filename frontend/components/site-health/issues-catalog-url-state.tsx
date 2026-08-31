'use client';

import { useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import { SearchField } from '@/components/ui/search-field';
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
  const selectedGroupId = urlParams.get('issue');

  const navigate = (nextFilters: IssueFilters, nextCursor: string | null) => {
    const nextParams = serializeIssueFilters(nextFilters, nextCursor, urlParams);
    nextParams.delete('issue');
    const nextQuery = nextParams.toString();
    const href = nextQuery ? `${pathname}?${nextQuery}` : pathname;
    const currentHref = searchParamString ? `${pathname}?${searchParamString}` : pathname;
    if (href !== currentHref) router.push(href, { scroll: false });
  };

  const selectIssue = (groupId: string) => {
    const nextParams = new URLSearchParams(urlParams);
    nextParams.set('issue', groupId);
    router.push(`${pathname}?${nextParams.toString()}`, { scroll: false });
  };

  return { cursor, filters, selectedGroupId, navigate, selectIssue };
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
      <SearchField
        value={draft}
        onValueChange={setDraft}
        placeholder="Search issues…"
        aria-label="Search issues"
        className="max-w-xs"
      />
    </form>
  );
}
