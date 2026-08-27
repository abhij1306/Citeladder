'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import type { CommerceTarget } from '@/lib/api/schemas/commerce-suite';

const KINDS = new Set(['category', 'product']);

/** `category:<uuid>` — the one spelling of a target, shared by URL and payload. */
export function targetKey(target: CommerceTarget): string {
  return `${target.kind}:${target.id}`;
}

export function parseTargetKey(value: string | null | undefined): CommerceTarget | undefined {
  const [kind, id] = (value ?? '').split(':');
  if (!KINDS.has(kind) || !id) return undefined;
  return { kind: kind as CommerceTarget['kind'], id };
}

/**
 * The selected Commerce target, held in the URL.
 *
 * There used to be three of these: `CompetitorsPanel` and `BuyerPromptsPanel`
 * each kept their own `useState`, and AI Shelf's lived further away again in
 * `products-screen.tsx`. One question — which category or product am I working
 * on? — answered in three places that never agreed, so switching view lost
 * your place and a reload lost all three. That is what made a target selector
 * necessary in every tab.
 *
 * In the URL it survives a reload, a deep link, and a back button, and it is
 * the same value the run payload is built from, so what is on screen is what
 * runs.
 */
export function useCommerceTarget() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const target = parseTargetKey(searchParams?.get('target'));
  const selectTarget = (next: CommerceTarget | undefined) => {
    const params = new URLSearchParams(searchParams?.toString() ?? '');
    // The legacy `?tab=` values are all views of a target now; drop the key so
    // an old link resolves to the workspace rather than a tab that is gone.
    params.delete('tab');
    if (next) params.set('target', targetKey(next));
    else params.delete('target');
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };
  return { target, selectTarget };
}
