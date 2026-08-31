'use client';

import { useCallback, useMemo, useSyncExternalStore } from 'react';

export type UrlCodec<T> = {
  parse: (raw: string | null) => T;
  serialize: (value: T) => string | null;
};

export type UrlHistory = 'push' | 'replace';

const URL_STATE_EVENT = 'citeladder:url-state';

function subscribe(listener: () => void): () => void {
  window.addEventListener('popstate', listener);
  window.addEventListener(URL_STATE_EVENT, listener);
  return () => {
    window.removeEventListener('popstate', listener);
    window.removeEventListener(URL_STATE_EVENT, listener);
  };
}

function browserLocation(): string {
  return `${window.location.pathname}${window.location.search}`;
}

export function useUrlState<T>(
  key: string,
  codec: UrlCodec<T>,
  options: Readonly<{ history?: UrlHistory; clearKeys?: readonly string[] }> = {},
): readonly [T, (value: T, history?: UrlHistory) => void] {
  const location = useSyncExternalStore(subscribe, browserLocation, () => '/');
  const currentUrl = useMemo(() => new URL(location, 'http://citeladder.local'), [location]);
  const value = useMemo(
    () => codec.parse(currentUrl.searchParams.get(key)),
    [codec, currentUrl.searchParams, key],
  );

  const setValue = useCallback(
    (next: T, history = options.history ?? 'push') => {
      const params = new URLSearchParams(currentUrl.searchParams);
      const encoded = codec.serialize(next);
      if (encoded === null) params.delete(key);
      else params.set(key, encoded);
      for (const ownedKey of options.clearKeys ?? []) params.delete(ownedKey);
      const href = params.size
        ? `${currentUrl.pathname}?${params.toString()}`
        : currentUrl.pathname;
      const method = history === 'push' ? 'pushState' : 'replaceState';
      window.history[method](window.history.state, '', href);
      window.dispatchEvent(new Event(URL_STATE_EVENT));
    },
    [codec, currentUrl, key, options.clearKeys, options.history],
  );

  return [value, setValue] as const;
}

export function stringUrlCodec<T extends string>(allowed: readonly T[], fallback: T): UrlCodec<T> {
  return {
    parse: (raw) => (allowed.includes(raw as T) ? (raw as T) : fallback),
    serialize: (value) => (value === fallback ? null : value),
  };
}

export const optionalStringUrlCodec: UrlCodec<string | null> = {
  parse: (raw) => raw,
  serialize: (value) => value,
};
