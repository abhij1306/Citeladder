import { Card, CardContent } from '@/components/ui/card';
import { ScoreRing } from '@/components/ui/score-ring';
import { Label } from '@/components/ui/typography';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import type { PageDetail } from '@/lib/api/types';

export function UrlScoreSummary({ detail }: Readonly<{ detail: PageDetail }>) {
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <ScoreTile
        label="Web Fundamentals"
        value={detail.web_fundamentals_score}
        coverage={detail.web_fundamentals_coverage}
        state={detail.web_fundamentals_state}
      />
      <ScoreTile
        label="AEO Readiness"
        value={detail.aeo_readiness_score}
        coverage={detail.aeo_measurement_coverage}
        state={detail.aeo_measurement_state}
      />
      <ScoreTile
        label="AEO Measurement Coverage"
        value={
          detail.aeo_measurement_coverage === null ? null : detail.aeo_measurement_coverage * 100
        }
        coverage={detail.aeo_measurement_coverage}
        state={detail.aeo_measurement_state}
      />
    </div>
  );
}

function ScoreTile({
  label,
  value,
  coverage,
  state,
}: Readonly<{ label: string; value: number | null; coverage: number | null; state: string }>) {
  const coverageLabel =
    coverage === null ? 'Coverage unavailable' : `${Math.round(coverage * 100)}% measured`;
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-2 py-[var(--card-padding)]">
        {value === null ? (
          scoreUnavailableState(state)
        ) : (
          <ScoreRing value={value} size={64} label={`${label}: ${Math.round(value)}`} />
        )}
        <Label>{label}</Label>
        <span className="text-muted text-center text-xs">
          {coverageLabel} · {scoreConfidenceLabel(state)}
        </span>
      </CardContent>
    </Card>
  );
}

function scoreUnavailableState(state: string) {
  if (state === 'limited_evidence') {
    return <span className="text-muted text-xs">Limited evidence</span>;
  }
  if (state === 'excluded') {
    return <span className="text-muted text-xs">Excluded</span>;
  }
  return <UnavailableValue state="not_measured" />;
}

function scoreConfidenceLabel(state: string): string {
  if (state === 'measured') return 'High confidence';
  if (state === 'limited_evidence') return 'Moderate confidence';
  if (state === 'excluded') return 'Excluded';
  return 'Not measured';
}
