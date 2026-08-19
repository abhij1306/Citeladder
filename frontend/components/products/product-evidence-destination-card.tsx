import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { ProductEvidenceItem } from '@/lib/api/types';
import { BUYER_DESTINATION_KIND_LABELS, formatPrice } from '@/lib/products/catalog';
import { engineLabel } from '@/lib/providers/catalog';

function DestinationEvidenceRow({ item }: Readonly<{ item: ProductEvidenceItem }>) {
  const hasMerchant = item.merchant_name !== null || item.merchant_domain !== null;
  return (
    <TableRow>
      <TableCell>
        <Badge variant="neutral">{engineLabel(item.logical_engine)}</Badge>
      </TableCell>
      <TableCell className="max-w-80">
        <span className="text-foreground line-clamp-2 block text-sm">{item.prompt_text}</span>
        <span className="text-muted text-xs">
          #{item.prompt_index} · rep {item.repetition}
        </span>
      </TableCell>
      <TableCell className="max-w-55">
        {hasMerchant ? (
          <div className="grid gap-0.5">
            <span className="text-foreground truncate font-medium">
              {item.merchant_name ?? item.merchant_domain}
            </span>
            {item.merchant_name !== null && item.merchant_domain !== null ? (
              <span className="text-muted truncate text-xs">{item.merchant_domain}</span>
            ) : null}
          </div>
        ) : (
          <span className="text-subtle">—</span>
        )}
      </TableCell>
      <TableCell>
        {item.merchant_kind !== null ? (
          <Badge variant="neutral">{BUYER_DESTINATION_KIND_LABELS[item.merchant_kind]}</Badge>
        ) : (
          <span className="text-subtle">—</span>
        )}
      </TableCell>
      <TableCell className="max-w-65">
        {item.destination_url !== null ? (
          <a
            href={item.destination_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-text block truncate text-sm hover:underline"
          >
            {item.destination_url}
          </a>
        ) : (
          <span className="text-subtle">—</span>
        )}
      </TableCell>
      <TableCell numeric className="text-secondary">
        {item.price_value !== null ? (
          <span title={item.price_text}>{formatPrice(item.price_value, item.price_currency)}</span>
        ) : (
          '—'
        )}
      </TableCell>
    </TableRow>
  );
}

export function DestinationEvidenceTable({ items }: Readonly<{ items: ProductEvidenceItem[] }>) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Engine</TableHead>
          <TableHead className="min-w-55">Prompt</TableHead>
          <TableHead>Merchant</TableHead>
          <TableHead>Kind</TableHead>
          <TableHead className="min-w-50">Destination URL</TableHead>
          <TableHead>Price</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <DestinationEvidenceRow key={item.evidence_id} item={item} />
        ))}
      </TableBody>
    </Table>
  );
}
