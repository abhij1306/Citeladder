'use client';

import { CheckCircle2, ExternalLink, Search, XCircle } from 'lucide-react';

import { MeasurementContext } from '@/components/runs/measurement-context';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/typography';
import { engineLabel, transportLabel } from '@/lib/providers/catalog';
import type { ExecutionEvidence } from '@/lib/api/types';
import { classificationBadgeValue, classificationLabel } from '@/lib/runs/status';
import { cn } from '@/lib/utils';

import { ContentMarkdown } from '@/lib/content/markdown';

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
    <div className="border-border-subtle bg-panel flex min-w-0 items-start gap-2.5 rounded-md border p-3 shadow-xs">
      <Icon
        className={cn('mt-0.5 size-4 shrink-0', passed ? 'text-score-high' : 'text-muted')}
        aria-hidden
      />
      <div className="min-w-0">
        <p className="text-foreground text-sm font-medium">{label}</p>
        <p className="text-muted text-xs leading-relaxed">{detail}</p>
      </div>
    </div>
  );
}

function EvidencePromptHeader({
  evidence,
  promptText,
  promptIndex,
  repetition,
}: Readonly<{
  evidence: ExecutionEvidence;
  promptText?: string | null;
  promptIndex?: number;
  repetition?: number;
}>) {
  const displayPrompt =
    promptText ||
    (promptIndex !== undefined
      ? `Prompt #${promptIndex + 1}`
      : `Prompt #${evidence.prompt_index + 1}`);
  const displayRepetition = repetition !== undefined ? repetition : evidence.repetition;
  const promptBadgeNumber = promptIndex !== undefined ? promptIndex + 1 : evidence.prompt_index + 1;

  return (
    <section className="border-border-subtle bg-panel grid min-w-0 gap-2.5 rounded-md border p-3.5 shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge variant="neutral">Prompt #{promptBadgeNumber}</Badge>
          <span className="mono text-muted text-2xs">rep {displayRepetition}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="neutral">
            {engineLabel(evidence.logical_engine)} · {transportLabel(evidence.transport_provider)}
          </Badge>
          <MeasurementContext
            retrieval={evidence.retrieval_enabled}
            model={evidence.transport_model}
          />
        </div>
      </div>
      <p className="text-foreground text-sm leading-snug font-medium">{displayPrompt}</p>
    </section>
  );
}

function EvidenceMetrics({ evidence }: Readonly<{ evidence: ExecutionEvidence }>) {
  return (
    <section className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-4">
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
    </section>
  );
}

function EvidenceAnswer({ answerText }: Readonly<{ answerText?: string | null }>) {
  const trimmed = answerText?.trim();
  return (
    <section className="grid gap-2">
      <Label>Engine response</Label>
      <div className="border-border-subtle bg-panel min-w-0 overflow-hidden rounded-md border p-3.5 shadow-xs sm:p-4">
        {trimmed ? (
          <ContentMarkdown markdown={trimmed} density="compact" />
        ) : (
          <span className="text-muted text-sm">
            No answer text was captured for this execution.
          </span>
        )}
      </div>
    </section>
  );
}

function EvidenceOutcomes({ evidence }: Readonly<{ evidence: ExecutionEvidence }>) {
  const brandDetail = evidence.brand_mentioned
    ? `First match at character ${evidence.brand_first_offset ?? 0}`
    : 'No tracked brand alias appeared in the answer';
  const ownedDetail = `${evidence.owned_citation_count} owned ${evidence.owned_citation_count === 1 ? 'source' : 'sources'} found`;
  const searchDetail = evidence.search_used
    ? `${evidence.search_query_count} ${evidence.search_query_count === 1 ? 'search' : 'searches'} recorded`
    : 'The provider did not report web search';
  const competitorDetail =
    evidence.competitors_mentioned.length > 0
      ? evidence.competitors_mentioned.join(', ')
      : 'No configured competitors appeared';

  return (
    <section className="grid gap-3">
      <div>
        <Label>Why it scored this way</Label>
        <p className="text-muted mt-0.5 text-xs">
          Deterministic checks against the persisted answer and source evidence.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Outcome label="Brand detected" detail={brandDetail} passed={evidence.brand_mentioned} />
        <Outcome
          label="Owned source cited"
          detail={ownedDetail}
          passed={evidence.owned_domain_cited}
        />
        <Outcome label="Grounded with search" detail={searchDetail} passed={evidence.search_used} />
        <Outcome
          label="Competitor pressure"
          detail={competitorDetail}
          passed={evidence.competitors_mentioned.length === 0}
        />
      </div>
    </section>
  );
}

function CitationItem({
  citation,
}: Readonly<{ citation: ExecutionEvidence['citations'][number] }>) {
  const href = safeCitationUrl(citation.url);
  const ordinal = citation.ordinal > 0 ? citation.ordinal : citation.ordinal + 1;
  const title = citation.title || citation.domain || citation.url;

  return (
    <li className="flex gap-3 p-3.5">
      <span className="mono text-muted mt-0.5 w-5 shrink-0 text-xs font-medium">{ordinal}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            {href ? (
              <a
                href={href}
                target="_blank"
                rel="noreferrer"
                className="text-foreground hover:text-accent-text inline-flex max-w-full items-center gap-1.5 text-sm font-medium transition-colors hover:underline"
              >
                <span className="truncate">{title}</span>
                <ExternalLink className="size-3 shrink-0" aria-hidden />
              </a>
            ) : (
              <p className="text-foreground truncate text-sm font-medium">
                {title || 'Untitled source'}
              </p>
            )}
            <p className="text-muted mt-0.5 truncate text-xs">{citation.domain}</p>
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
}

function EvidenceCitationsList({
  citations,
}: Readonly<{ citations: ExecutionEvidence['citations'] }>) {
  return (
    <section className="grid gap-3">
      <div className="flex items-center justify-between gap-2">
        <Label>Citations</Label>
        <span className="text-muted text-xs">
          {citations.length} {citations.length === 1 ? 'source' : 'sources'}
        </span>
      </div>
      {citations.length === 0 ? (
        <div className="border-border-subtle text-muted rounded-lg border border-dashed p-4 text-center text-sm">
          No citations were captured from this response.
        </div>
      ) : (
        <ol className="divide-border-subtle border-border-subtle bg-panel divide-y rounded-md border shadow-xs">
          {citations.map((citation) => (
            <CitationItem key={`${citation.ordinal}-${citation.url}`} citation={citation} />
          ))}
        </ol>
      )}
    </section>
  );
}

function EvidenceFooter({ evidence }: Readonly<{ evidence: ExecutionEvidence }>) {
  return (
    <footer className="border-border-subtle text-muted flex flex-wrap items-center gap-x-4 gap-y-1 border-t pt-3 text-xs">
      <span className="inline-flex items-center gap-1">
        <Search className="size-3" aria-hidden />
        {evidence.prompt_class.replace(/_/g, ' ')} prompt
      </span>
      <span>Analyzer {evidence.analyzer_version}</span>
      <span>Rules {evidence.scoring_rule_version}</span>
    </footer>
  );
}

/** Clear, persisted explanation of one execution's deterministic evidence. */
export function EvidenceCard({
  evidence,
  answerText,
  promptText,
  promptIndex,
  repetition,
}: Readonly<{
  evidence: ExecutionEvidence;
  answerText?: string | null;
  promptText?: string | null;
  promptIndex?: number;
  repetition?: number;
}>) {
  return (
    <div className="grid min-w-0 gap-[var(--workspace-gap)]">
      <EvidencePromptHeader
        evidence={evidence}
        promptText={promptText}
        promptIndex={promptIndex}
        repetition={repetition}
      />
      <EvidenceMetrics evidence={evidence} />
      <EvidenceAnswer answerText={answerText} />
      <EvidenceOutcomes evidence={evidence} />
      <EvidenceCitationsList citations={evidence.citations} />
      <EvidenceFooter evidence={evidence} />
    </div>
  );
}

function EvidenceStat({
  label,
  value,
  positive,
}: Readonly<{ label: string; value: string; positive?: boolean }>) {
  return (
    <div className="border-border-subtle bg-panel grid min-w-0 gap-0.5 rounded-md border px-3 py-2.5 shadow-xs">
      <span className="text-muted text-xs">{label}</span>
      <span
        className={cn(
          'truncate text-sm font-semibold',
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
