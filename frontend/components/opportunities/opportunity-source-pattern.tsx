import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/typography';
import {
  recommendedActionLabel,
  sourceClassBadgeValue,
  sourceClassLabel,
  type SourcePattern,
} from '@/lib/opportunities/source-pattern';

/**
 * Observed source pattern for a visibility opportunity.
 *
 * Answers "what kinds of sources did the engines cite where you were not
 * cited" using the citations the audit already persisted. Every string here is
 * deliberately observational — "observed", "appears alongside" — because the
 * data supports no causal claim that a cited source produced the
 * recommendation. Do not reword this toward "because" or "caused by".
 */
export function OpportunitySourcePattern({ pattern }: Readonly<{ pattern: SourcePattern }>) {
  const action = recommendedActionLabel(pattern.recommendedAction);

  return (
    <section className="grid gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <Label>Observed sources</Label>
        <span className="text-2xs text-muted">
          {pattern.distinctDomainCount} {pattern.distinctDomainCount === 1 ? 'domain' : 'domains'}
          {pattern.independentDomainCount > 0
            ? ` · ${pattern.independentDomainCount} independent`
            : null}
        </span>
      </div>

      {pattern.classCounts.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {pattern.classCounts.map(({ sourceClass, count }) => (
            <Badge
              key={sourceClass}
              variant="classification"
              value={sourceClassBadgeValue(sourceClass)}
            >
              {sourceClassLabel(sourceClass)} · {count}
            </Badge>
          ))}
        </div>
      ) : null}

      {pattern.competitorSourceDomains.length > 0 ? (
        <div className="grid gap-1">
          <span className="text-2xs text-muted">Sources matched to a tracked competitor</span>
          {pattern.competitorSourceDomains.map(({ competitor, domains }) => (
            <div key={competitor} className="flex items-start justify-between gap-3 py-0.5">
              <span className="text-secondary shrink-0 text-sm">{competitor}</span>
              <span className="mono text-muted text-right text-xs break-all">
                {domains.join(', ')}
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {pattern.topCitations.length > 0 ? (
        <ul className="grid gap-1">
          {pattern.topCitations.map((citation) => (
            <li
              key={citation.url || citation.domain}
              className="border-border-subtle bg-panel grid gap-0.5 rounded-md border px-3 py-2 shadow-xs"
            >
              <span className="text-foreground text-xs">{citation.title || citation.domain}</span>
              <span className="mono text-muted text-2xs break-all">{citation.domain}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {pattern.topCitationsTruncated ? (
        <p className="text-2xs text-muted">
          Showing the first {pattern.topCitations.length} of {pattern.distinctDomainCount} cited
          domains. Every citation stays available in Visibility → Mentions &amp; Citations.
        </p>
      ) : null}

      {action ? (
        <div className="border-accent-border bg-accent-subtle rounded-md border-l px-3 py-2.5">
          <span className="text-2xs text-muted">Suggested next action</span>
          <p className="text-foreground text-sm">{action}</p>
        </div>
      ) : null}
    </section>
  );
}
