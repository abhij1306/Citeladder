'use client';

import { CheckCircle2, ExternalLink, Search, XCircle } from 'lucide-react';

import { MeasurementContext } from '@/components/runs/measurement-context';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/typography';
import { engineLabel, transportLabel } from '@/lib/providers/catalog';
import type { ExecutionEvidence } from '@/lib/api/types';
import { classificationBadgeValue, classificationLabel } from '@/lib/runs/status';
import { cn } from '@/lib/utils';

function safeCitationUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : null;
  } catch {
    return null;
  }
}

function Outcome({
  label,
  detail,
  passed,
}: Readonly<{ label: string; detail: string; passed: boolean }>) {
  const Icon = passed ? CheckCircle2 : XCircle;
  return (
    <div className="flex min-w-0 items-start gap-2">
      <Icon
        className={cn('mt-0.5 size-4 shrink-0', passed ? 'text-score-high' : 'text-muted')}
        aria-hidden
      />
      <div className="min-w-0">
        <p className="text-foreground text-sm font-medium">{label}</p>
        <p className="text-muted text-xs">{detail}</p>
      </div>
    </div>
  );
}

/** Clear, persisted explanation of one execution's deterministic evidence. */
export function EvidenceCard({
  evidence,
  answerText,
}: Readonly<{ evidence: ExecutionEvidence; answerText?: string | null }>) {
  return (
    <div className="grid gap-6">
      <section className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="neutral">
            {engineLabel(evidence.logical_engine)} · {transportLabel(evidence.transport_provider)}
          </Badge>
          <MeasurementContext
            retrieval={evidence.retrieval_enabled}
            model={evidence.transport_model}
          />
        </div>

        <div className="border-border-subtle grid grid-cols-2 border-y sm:grid-cols-4">
          <EvidenceStat
            label="Brand"
            value={evidence.brand_mentioned ? 'Mentioned' : 'Not mentioned'}
            positive={evidence.brand_mentioned}
          />
          <EvidenceStat
            label="Owned sources"
            value={String(evidence.owned_citation_count)}
            positive={evidence.owned_citation_count > 0}
          />
          <EvidenceStat label="Citations" value={String(evidence.citation_count)} />
          <EvidenceStat
            label="Searches"
            value={evidence.search_used ? String(evidence.search_query_count) : 'Not used'}
            positive={evidence.search_used}
          />
        </div>
      </section>

      <section className="grid gap-2">
        <Label>Answer</Label>
        <div className="bg-background-alt rounded-lg p-4">
          <p className="text-foreground text-sm leading-relaxed whitespace-pre-wrap">
            {answerText?.trim() || (
              <span className="text-muted">No answer text was captured for this execution.</span>
            )}
          </p>
        </div>
      </section>

      <section className="grid gap-3">
        <div>
          <Label>Why it scored this way</Label>
          <p className="text-muted mt-1 text-xs">
            Deterministic checks against the persisted answer and source evidence.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Outcome
            label="Brand detected"
            detail={
              evidence.brand_mentioned
                ? `First match at character ${evidence.brand_first_offset ?? 0}`
                : 'No tracked brand alias appeared in the answer'
            }
            passed={evidence.brand_mentioned}
          />
          <Outcome
            label="Owned source cited"
            detail={`${evidence.owned_citation_count} owned ${evidence.owned_citation_count === 1 ? 'source' : 'sources'} found`}
            passed={evidence.owned_domain_cited}
          />
          <Outcome
            label="Grounded with search"
            detail={
              evidence.search_used
                ? `${evidence.search_query_count} ${evidence.search_query_count === 1 ? 'search' : 'searches'} recorded`
                : 'The provider did not report web search'
            }
            passed={evidence.search_used}
          />
          <Outcome
            label="Competitor pressure"
            detail={
              evidence.competitors_mentioned.length > 0
                ? evidence.competitors_mentioned.join(', ')
                : 'No configured competitors appeared'
            }
            passed={evidence.competitors_mentioned.length === 0}
          />
        </div>
      </section>

      <section className="grid gap-3">
        <div className="flex items-center justify-between gap-2">
          <Label>Citations</Label>
          <span className="text-muted text-xs">
            {evidence.citations.length} {evidence.citations.length === 1 ? 'source' : 'sources'}
          </span>
        </div>
        {evidence.citations.length === 0 ? (
          <div className="border-border-subtle text-muted rounded-lg border border-dashed p-4 text-sm">
            No citations were captured from this response.
          </div>
        ) : (
          <ol className="border-border-subtle divide-border-subtle divide-y rounded-lg border">
            {evidence.citations.map((citation) => {
              const href = safeCitationUrl(citation.url);
              return (
                <li key={`${citation.ordinal}-${citation.url}`} className="flex gap-3 p-3">
                  <span className="mono text-muted mt-0.5 w-5 shrink-0 text-xs">
                    {citation.ordinal > 0 ? citation.ordinal : citation.ordinal + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        {href ? (
                          <a
                            href={href}
                            target="_blank"
                            rel="noreferrer"
                            className="text-foreground inline-flex max-w-full items-center gap-1 text-sm font-medium hover:underline"
                          >
                            <span className="truncate">
                              {citation.title || citation.domain || citation.url}
                            </span>
                            <ExternalLink className="size-3 shrink-0" aria-hidden />
                          </a>
                        ) : (
                          <p className="text-foreground truncate text-sm font-medium">
                            {citation.title || citation.domain || 'Untitled source'}
                          </p>
                        )}
                        <p className="text-muted truncate text-xs">{citation.domain}</p>
                      </div>
                      <Badge
                        className="shrink-0"
                        variant="classification"
                        value={classificationBadgeValue(citation.classification)}
                      >
                        {classificationLabel(citation.classification)}
                      </Badge>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </section>

      <footer className="border-border-subtle text-muted flex flex-wrap items-center gap-x-4 gap-y-1 border-t pt-3 text-xs">
        <span className="inline-flex items-center gap-1">
          <Search className="size-3" aria-hidden />
          {evidence.prompt_class.replace(/_/g, ' ')} prompt
        </span>
        <span>Analyzer {evidence.analyzer_version}</span>
        <span>Rules {evidence.scoring_rule_version}</span>
      </footer>
    </div>
  );
}

function EvidenceStat({
  label,
  value,
  positive,
}: Readonly<{ label: string; value: string; positive?: boolean }>) {
  return (
    <div className="border-border-subtle grid min-w-0 gap-1 border-e p-3 last:border-e-0 even:border-e-0 sm:last:border-e-0 sm:even:border-e">
      <span className="text-muted text-xs">{label}</span>
      <span
        className={cn(
          'truncate text-sm font-medium',
          positive === true
            ? 'text-score-high'
            : positive === false
              ? 'text-muted'
              : 'text-foreground',
        )}
      >
        {value}
      </span>
    </div>
  );
}
