'use client';

import { AgentPreview } from './product-preview/agent-preview';
import { ContentPreview } from './product-preview/content-preview';
import { DemandPreview } from './product-preview/demand-preview';
import { SitePreview } from './product-preview/site-preview';

export type ProductLayerId = 'site' | 'content' | 'demand' | 'agent';

type ProductPreviewPanelProps = Readonly<{
  layer: ProductLayerId;
  phase: number;
  reduceMotion: boolean;
}>;

export function ProductPreviewPanel({ layer, phase, reduceMotion }: ProductPreviewPanelProps) {
  if (layer === 'site') return <SitePreview phase={phase} reduceMotion={reduceMotion} />;
  if (layer === 'content') return <ContentPreview phase={phase} reduceMotion={reduceMotion} />;
  if (layer === 'demand') return <DemandPreview phase={phase} reduceMotion={reduceMotion} />;
  return <AgentPreview phase={phase} reduceMotion={reduceMotion} />;
}
