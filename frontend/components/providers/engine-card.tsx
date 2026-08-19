'use client';

import type { ProviderConnection } from '@/lib/api/types';
import type { EngineCardModel } from '@/lib/providers/catalog';
import { useEngineConnection } from '@/lib/providers/use-engine-connection';

import { EngineCardView } from './engine-card-view';

/** Provider-card controller. Connection state and all display branches live in the view. */
export function EngineCard({
  model,
  connections,
}: Readonly<{ model: EngineCardModel; connections: ProviderConnection[] }>) {
  const connectionState = useEngineConnection({ model, connections });
  return <EngineCardView model={model} connectionState={connectionState} />;
}
