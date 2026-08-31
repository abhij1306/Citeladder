import type { IssueOccurrence } from '@/lib/api/types';

type Evidence = Record<string, unknown>;

const FALLBACK_LIMIT = 6;
const FALLBACK_VALUE_CHARS = 160;
const GROUP_LEVEL_FIELDS = new Set(['reason', 'reason_code']);

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.length > 0)
    : [];
}

function headingStatements(evidence: Evidence): string[] {
  if (!Array.isArray(evidence.skips)) return [];
  return evidence.skips.flatMap((value) => {
    if (!value || typeof value !== 'object') return [];
    const skip = value as Evidence;
    if (typeof skip.from !== 'number' || typeof skip.to !== 'number') return [];
    const scope = skip.scope === 'primary_content' ? ', primary content' : ', full document';
    return [`H${skip.from} → H${skip.to}${scope}.`];
  });
}

function schemaStatements(evidence: Evidence): string[] {
  const expected = strings(evidence.expected_types);
  const found = strings(evidence.found_types);
  const missing = strings(evidence.missing);
  const schemaType = typeof evidence.schema_type === 'string' ? evidence.schema_type : expected[0];
  const lines: string[] = [];
  if (expected.length > 0 && 'found_types' in evidence) {
    lines.push(
      `Expected ${expected.join(' or ')}; found ${found.length > 0 ? found.join(', ') : 'none'}.`,
    );
  }
  if (missing.length > 0) {
    lines.push(`${schemaType || 'Expected schema'} is missing ${missing.join(', ')}.`);
  }
  if (typeof evidence.checked_blocks === 'number') {
    lines.push(
      `Checked ${evidence.checked_blocks} schema ${evidence.checked_blocks === 1 ? 'block' : 'blocks'}.`,
    );
  }
  if (evidence.extraction === 'microdata_shallow') {
    lines.push('Property extraction was limited for shallow microdata.');
  }
  return lines;
}

function descriptorLabel(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Evidence;
  const parts = [
    typeof item.tag === 'string' ? item.tag : null,
    typeof item.type === 'string' && item.type ? `type=${item.type}` : null,
    typeof item.id === 'string' && item.id ? `id=${item.id}` : null,
    typeof item.name === 'string' && item.name ? `name=${item.name}` : null,
    typeof item.ordinal === 'number' ? `#${item.ordinal}` : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(' · ') : null;
}

function formStatements(evidence: Evidence): string[] {
  if (typeof evidence.missing_accessible_name !== 'number') return [];
  const total = typeof evidence.control_count === 'number' ? evidence.control_count : null;
  const count = evidence.missing_accessible_name;
  const lines = [
    total === null
      ? `${count} ${count === 1 ? 'control lacks' : 'controls lack'} an accessible name.`
      : `${count} of ${total} controls lack accessible names.`,
  ];
  if (Array.isArray(evidence.missing_control_descriptors)) {
    lines.push(
      ...evidence.missing_control_descriptors
        .map(descriptorLabel)
        .filter((value): value is string => value !== null),
    );
  }
  return lines;
}

function brokenLinkStatements(evidence: Evidence): string[] {
  if (!Array.isArray(evidence.failing_targets)) return [];
  return evidence.failing_targets.slice(0, 10).flatMap((value) => {
    if (!value || typeof value !== 'object') return [];
    const target = value as Evidence;
    if (typeof target.url !== 'string' || typeof target.status_code !== 'number') return [];
    return [`Link target ${target.url} returned HTTP ${target.status_code}.`];
  });
}

function fallbackValue(value: unknown): string | null {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value).slice(0, FALLBACK_VALUE_CHARS);
  }
  if (Array.isArray(value)) {
    const values = value
      .filter((item) => ['string', 'number', 'boolean'].includes(typeof item))
      .slice(0, 5)
      .map((item) => String(item).slice(0, FALLBACK_VALUE_CHARS));
    return values.length > 0 ? values.join(', ') : null;
  }
  return null;
}

function humanize(key: string): string {
  return key.replaceAll('_', ' ').replace(/^./, (value) => value.toUpperCase());
}

export function evidenceStatements(evidence: Evidence): string[] {
  const known = [
    ...headingStatements(evidence),
    ...schemaStatements(evidence),
    ...formStatements(evidence),
    ...brokenLinkStatements(evidence),
  ];
  if (known.length > 0) return known;

  return Object.entries(evidence)
    .flatMap(([key, value]) => {
      if (GROUP_LEVEL_FIELDS.has(key)) return [];
      const formatted = fallbackValue(value);
      return formatted === null ? [] : [`${humanize(key)}: ${formatted}.`];
    })
    .slice(0, FALLBACK_LIMIT);
}

export function IssueEvidence({ occurrence }: Readonly<{ occurrence: IssueOccurrence }>) {
  const statements = evidenceStatements(occurrence.evidence);
  return (
    <div className="grid gap-1.5">
      <span className="text-2xs text-muted font-medium">Observed evidence</span>
      {statements.length > 0 ? (
        <ul className="text-secondary grid gap-1 text-sm">
          {statements.map((statement, index) => (
            <li key={`${occurrence.occurrence_id}-${index}`}>{statement}</li>
          ))}
        </ul>
      ) : (
        <p className="text-secondary text-sm">No bounded evidence was recorded.</p>
      )}
    </div>
  );
}
