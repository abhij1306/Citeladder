'use client';

import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';

import { brandDiscoveriesApi, type BrandDiscoveryInput } from '@/lib/api/brand-discoveries';

let fallbackOperationSequence = 0;

function operationKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  fallbackOperationSequence += 1;
  return `discovery-${Date.now()}-${fallbackOperationSequence}`;
}

export function useBrandDiscovery(
  input: BrandDiscoveryInput | null,
  resumeId: string | null = null,
) {
  const fingerprint = useMemo(() => JSON.stringify(input), [input]);
  const createdFor = useRef<string | null>(null);
  const [responseFor, setResponseFor] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: ({
      payload,
      idempotencyKey,
    }: {
      payload: BrandDiscoveryInput;
      idempotencyKey: string;
    }) => brandDiscoveriesApi.create(payload, idempotencyKey),
    onSuccess: (_data, { payload }) => {
      setResponseFor(JSON.stringify(payload));
    },
  });

  useEffect(() => {
    if (resumeId || !input || createdFor.current === fingerprint) return;
    createdFor.current = fingerprint;
    create.mutate({ payload: input, idempotencyKey: operationKey() });
  }, [create, fingerprint, input, resumeId]);

  const createdDiscoveryId = responseFor === fingerprint ? create.data?.id : undefined;
  // A successful retry supersedes a resumed row. Until that response arrives,
  // the persisted resume id remains visible instead of blanking the timeline.
  const discoveryId = createdDiscoveryId ?? resumeId;
  const query = useQuery({
    queryKey: ['brand-discovery', discoveryId],
    queryFn: ({ signal }) => brandDiscoveriesApi.get(discoveryId!, { signal }),
    enabled: Boolean(discoveryId),
    initialData: !createdDiscoveryId ? undefined : create.data,
    // `completing` is the portfolio generation the completion request queued.
    // It runs on a worker precisely because it outlives a client request, so
    // this poll is how the review screen learns the project exists.
    refetchInterval: (result) =>
      result.state.data?.status === 'queued' ||
      result.state.data?.status === 'running' ||
      result.state.data?.status === 'completing'
        ? 1000
        : false,
  });
  const discovery = query.data ?? (createdDiscoveryId ? create.data : undefined);
  const retry = () => {
    if (!input || create.isPending) return;
    createdFor.current = fingerprint;
    create.mutate({ payload: input, idempotencyKey: operationKey() });
  };
  return {
    discovery,
    isRunning:
      create.isPending || discovery?.status === 'queued' || discovery?.status === 'running',
    error: create.error ?? query.error,
    retry,
  };
}
