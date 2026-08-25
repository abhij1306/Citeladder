import { OpportunityKvRow } from '@/components/opportunities/opportunity-kv-row';
import { OpportunitySourcePattern } from '@/components/opportunities/opportunity-source-pattern';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/typography';
import type { OpportunityDetail } from '@/lib/api/types';
import { parseSourcePattern } from '@/lib/opportunities/source-pattern';

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : [];
}

export function OpportunityEvidenceSection({ detail }: Readonly<{ detail: OpportunityDetail }>) {
  const evidence = detail.evidence;
  const promptText = asString(evidence.prompt_text);
  const url = asString(evidence.url) ?? detail.target_url;
  const theme = asString(evidence.prompt_theme) ?? detail.target_theme;
  const competitors = asStringList(evidence.competitor_names);
  const sourcePattern = parseSourcePattern(evidence);

  return (
    <section className="grid gap-2">
      <Label>Evidence</Label>
      {promptText ? (
        <blockquote className="border-accent-border bg-accent-subtle rounded-md border-l px-3 py-2.5">
          <p className="text-foreground text-sm leading-snug">“{promptText}”</p>
        </blockquote>
      ) : null}
      {url ? (
        <p className="mono text-accent-text bg-background-alt rounded-md px-3 py-2 text-xs break-all">
          {url}
        </p>
      ) : null}
      {theme ? <OpportunityKvRow label="Topic" value={theme} /> : null}
      {competitors.length > 0 ? (
        <div className="grid gap-1">
          <span className="text-2xs text-muted">Competitors mentioned</span>
          <div className="flex flex-wrap gap-1.5">
            {competitors.map((name) => (
              <Badge key={name} variant="classification" value="competitor">
                {name}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}
      {sourcePattern ? <OpportunitySourcePattern pattern={sourcePattern} /> : null}
    </section>
  );
}
