import Link from 'next/link';

import { OpportunityKvRow } from '@/components/opportunities/opportunity-kv-row';
import { Label } from '@/components/ui/typography';
import type { OpportunityDetail } from '@/lib/api/types';
import { formatAudited } from '@/lib/site-health/status';

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

/** One deep-link row in the Source list (label + accent link, like the tables). */
function SourceLink({
  label,
  href,
  linkText,
}: Readonly<{ label: string; href: string; linkText: string }>) {
  return (
    <div className="flex items-start justify-between gap-3 py-1">
      <span className="text-muted shrink-0 text-xs">{label}</span>
      <Link href={href} className="text-accent-text text-sm font-medium hover:underline">
        {linkText}
      </Link>
    </div>
  );
}

/**
 * Customer-useful source links for the finding. Persistence provenance stays
 * in the API for auditability but is not product copy.
 */
export function OpportunitySummarySection({ detail }: Readonly<{ detail: OpportunityDetail }>) {
  const evidence = detail.evidence;
  const auditId = asString(evidence.audit_id);
  const crawlId = asString(evidence.crawl_id);
  const siteUrlId = asString(evidence.site_url_id);

  return (
    <section className="grid gap-2">
      <Label>Supporting result</Label>
      <div className="divide-border-subtle divide-y">
        <OpportunityKvRow label="Found" value={formatAudited(detail.created_at)} />
        {auditId ? (
          <SourceLink label="Visibility review" href={`/runs/${auditId}`} linkText="View result" />
        ) : null}
        {crawlId && siteUrlId ? (
          <SourceLink
            label="Website page"
            href={`/site/crawls/${crawlId}/pages/${siteUrlId}`}
            linkText="View page"
          />
        ) : null}
        {detail.target_prompt_id ? (
          <SourceLink label="Question" href="/prompts" linkText="Open prompt library" />
        ) : null}
      </div>
    </section>
  );
}
