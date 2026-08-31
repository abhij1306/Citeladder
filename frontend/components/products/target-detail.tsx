'use client';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import type { CommerceTarget } from '@/lib/api/schemas/commerce-suite';
import { targetKey } from '@/lib/products/use-commerce-target';
import type { useCompetitorDiscovery } from '@/lib/products/competitor-discovery';

import type { CommerceQueries } from './commerce-queries';
import { TargetCompetitors } from './target-competitors';
import { TargetCorrections } from './target-corrections';
import { TargetPrompts } from './target-prompts';
import { TargetShelfBand, hasShelfMeasurement } from './target-shelf-band';

/**
 * Everything about ONE target, in the order it is asked about.
 *
 * Shelf metrics are the outcome and lead; the competitors and prompts that
 * produced them sit beneath. Each of these was a separate tab with its own
 * copy of the target selector, so a merchandiser could never see a category's
 * position and the competitors on that position at the same time.
 */
export function TargetDetail({
  projectId,
  target,
  label,
  queries,
  discovery,
}: Readonly<{
  projectId: string;
  target: CommerceTarget;
  label: string;
  queries: CommerceQueries;
  discovery: ReturnType<typeof useCompetitorDiscovery>;
}>) {
  return (
    <div className="grid content-start gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-foreground text-lg font-medium tracking-[-0.015em]">{label}</h2>
        <Badge variant="status" value="info">
          {target.kind}
        </Badge>
        <div className="ml-auto">
          <TargetCorrections
            key={targetKey(target)}
            projectId={projectId}
            target={target}
            catalog={queries.catalog.data}
          />
        </div>
      </div>
      <TargetShelfBand query={queries.shelf} />
      {hasShelfMeasurement(queries.shelf) ? null : (
        <Alert tone="info">
          This target has not been measured yet. Approve prompts below and launch an audit to
          produce shelf metrics.
        </Alert>
      )}
      <TargetCompetitors
        projectId={projectId}
        target={target}
        query={queries.competitors}
        discovery={discovery}
      />
      <TargetPrompts
        projectId={projectId}
        target={target}
        targetLabel={label}
        query={queries.buyerPrompts}
      />
    </div>
  );
}
