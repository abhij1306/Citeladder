import { Badge } from '@/components/ui/badge';
import type { OpportunityType } from '@/lib/api/types';
import { cn } from '@/lib/utils';

const TYPE_LABEL: Record<OpportunityType, string> = {
  visibility: 'Visibility',
  commerce: 'Commerce',
  site: 'Site',
  traffic: 'Traffic',
  topic: 'Topic',
};

export function OpportunityTypeBadge({ type }: Readonly<{ type: OpportunityType }>) {
  return (
    <Badge
      className={cn(
        (type === 'visibility' || type === 'commerce') && 'text-accent-text',
        type === 'site' && 'text-info-text',
        (type === 'topic' || type === 'traffic') && 'text-citation-third-party-text',
      )}
    >
      {TYPE_LABEL[type]}
    </Badge>
  );
}
