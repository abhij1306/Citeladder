/**
 * Turns a demand signal into a content brief.
 *
 * The Content agent is grounded in site evidence but knows nothing about *why*
 * it was invoked. Arriving from Search Demand we already know the subject, its
 * measured performance, and which deficiency the detector found — so the brief
 * states the objective in those terms instead of leaving the agent to guess
 * from a bare topic.
 *
 * The brief comes in two shapes, because the two kinds of signal ask for
 * different work:
 *
 *   - **A page signal** names a URL that already exists and underperforms.
 *     The brief is a REMEDIATION brief: rewrite that page, correcting the
 *     specific defect the detector found, and keep its route.
 *   - **A query signal** names demand with no adequate page behind it. The
 *     brief is a RANKING brief: create new content built to rank for it.
 *
 * Every number in the output is read from the signal; nothing is estimated,
 * and an unobserved metric is omitted rather than defaulted to zero.
 */
import type { DemandSignal } from '@/lib/api/demand';
import {
  competingPages,
  numericMetric,
  signalTarget,
  signalTargetKind,
} from '@/lib/demand/signals';

/** Query param the Content screen reads to rebuild a brief. */
export const DEMAND_SIGNAL_PARAM = 'demand_signal_id';

/**
 * Link into the Content screen seeded by this signal.
 *
 * Only the signal id travels in the URL: the brief is rebuilt on arrival from
 * the live snapshot, so a shared link never carries a stale copy of numbers
 * that have since been recomputed.
 */
export function contentBriefHref(signal: { id: string }): string {
  return `/content?${DEMAND_SIGNAL_PARAM}=${encodeURIComponent(signal.id)}`;
}

export type DemandBrief = {
  /** Ready-to-send prompt text. */
  prompt: string;
  /** Skill that fits this deficiency; the user can override it. */
  suggestedSkillId: string;
  /** Short label for the provenance chip on the Content screen. */
  sourceLabel: string;
};

/** Fixing an existing URL is page work; unmet query demand needs a new post. */
const PAGE_SKILL = 'content_page';
const QUERY_SKILL = 'blog';

type SignalSpec = {
  label: string;
  /** Why the detector fired, in the reader's terms. */
  objective: string;
  /** The corrections that resolve this defect on an existing page. */
  fixes: readonly string[];
};

const SIGNAL_SPECS: Record<string, SignalSpec> = {
  striking_distance: {
    label: 'Striking distance',
    objective:
      'This already ranks on page one or two but not high enough to earn clicks. It needs ' +
      'to cover the query more completely and more directly than it currently does.',
    fixes: [
      'Answer the query explicitly and completely — thin or partial coverage is what caps the ranking.',
      'Add the sub-questions a searcher asks next, each under its own heading.',
      'Replace generic phrasing with specifics: named entities, numbers, and concrete procedures.',
      'Make the H1 and opening paragraph match the query wording a searcher actually uses.',
    ],
  },
  query_cannibalization: {
    label: 'Cannibalization',
    objective:
      'Several of our own pages rank for this query and split its impressions between them, ' +
      'so no single page accumulates enough authority to win it.',
    fixes: [
      'Make this the one definitive page for the query — it must absorb the ground the competing URLs each cover only partially.',
      'Cover every distinct angle the competing pages hold, so none of them retains a reason to rank.',
      'Note which competing URLs should later be consolidated or redirected into this one.',
      'Keep the focus tight: do not introduce new sections that would compete with our other pages.',
    ],
  },
  property_relative_ctr_gap: {
    label: 'CTR gap',
    objective:
      'This under-converts its impressions relative to other results at the same ranking ' +
      'position. The ranking is not the problem — the result is not compelling enough to click.',
    fixes: [
      'Rewrite the meta title (60 characters or fewer) to lead with the query and its payoff.',
      'Rewrite the meta description (155 characters or fewer) to state what the reader gets, not what the page is about.',
      'Answer the query in the first sentence of the body, before any context or preamble.',
      'Add a short summary block near the top that a search result can quote directly.',
    ],
  },
  high_impression_low_ctr: {
    label: 'Low CTR',
    objective:
      'This is seen often but clicked rarely, which means the search intent behind the ' +
      'query is not being met by what the result promises.',
    fixes: [
      'Identify what the searcher actually wants and answer exactly that in the opening lines.',
      'Rewrite the meta title and description so they promise that answer.',
      'Remove any framing that suggests the page is about something adjacent to the query.',
    ],
  },
  emerging_query: {
    label: 'Emerging query',
    objective: 'Demand for this is growing quickly and we have no adequate coverage of it yet.',
    fixes: [
      'Add dedicated, prominent coverage of this query rather than a passing mention.',
      'Cover it thoroughly enough to claim the topic before the trend matures.',
    ],
  },
  declining_query: {
    label: 'Declining query',
    objective:
      'Demand for this is falling and the existing coverage has likely gone stale relative ' +
      'to what now ranks.',
    fixes: [
      'Refresh every factual detail and remove anything no longer accurate.',
      'Cover what has changed since the page was written, rather than restating the old answer.',
      'Update the angle to match what searchers now want from this query.',
    ],
  },
  branded_query_performance: {
    label: 'Branded query',
    objective:
      'This is navigational demand for our own brand — people searching this way have a ' +
      'specific question about us.',
    fixes: [
      'Answer the questions people actually ask about the brand when they search this way.',
      'Keep it factual and navigational; this is not a persuasion surface.',
    ],
  },
};

const FALLBACK: SignalSpec = {
  label: 'Demand signal',
  objective: 'Search Console shows unmet demand here that the current content does not satisfy.',
  fixes: ['Answer the query directly and completely.'],
};

/** Measured lines, omitting any metric the snapshot did not observe. */
function measuredLines(signal: DemandSignal): string[] {
  const lines: string[] = [];
  const impressions = numericMetric(signal, 'impressions');
  const clicks = numericMetric(signal, 'clicks');
  const ctr = numericMetric(signal, 'ctr');
  const position = numericMetric(signal, 'position');

  if (impressions !== null) lines.push(`- Impressions: ${impressions.toLocaleString('en-US')}`);
  if (clicks !== null) lines.push(`- Clicks: ${clicks.toLocaleString('en-US')}`);
  if (ctr !== null) lines.push(`- Click-through rate: ${(ctr * 100).toFixed(1)}%`);
  if (position !== null) lines.push(`- Average position: ${position.toFixed(1)}`);

  const cohortMedian = numericMetric(signal, 'cohort_median_ctr');
  if (cohortMedian !== null) {
    lines.push(
      `- Median click-through rate for this position band: ${(cohortMedian * 100).toFixed(1)}%`,
    );
  }
  return lines;
}

/** Competing URLs, so a cannibalization brief knows what it must consolidate. */
function competingLines(signal: DemandSignal): string[] {
  const pages = competingPages(signal);
  if (pages.length === 0) return [];
  return [
    '',
    'Pages currently competing for this query:',
    ...pages.map(
      (page) =>
        `- ${page.url} (${page.impressions.toLocaleString('en-US')} impressions, ` +
        `${(page.share * 100).toFixed(0)}% of the query's share)`,
    ),
  ];
}

/** Rewrite an existing URL, correcting the defect the detector identified. */
function pageBrief(signal: DemandSignal, spec: SignalSpec, target: string): string[] {
  const url = signal.page_url || target;
  return [
    `Rewrite the existing page at ${url}.`,
    '',
    'What is wrong with it:',
    spec.objective,
    '',
    'Fix these specific things:',
    ...spec.fixes.map((fix) => `- ${fix}`),
    '',
    'Keep the page at its current route and preserve the subject it already covers — this ' +
      'is a corrective rewrite of an existing page, not a new page on a new URL.',
  ];
}

/** Create new content built to rank for a query we do not adequately serve. */
function queryBrief(signal: DemandSignal, spec: SignalSpec, target: string): string[] {
  const sections = [
    `Write content built to rank for the search query "${target}".`,
    '',
    'Why this query needs content:',
    spec.objective,
    '',
    'To rank for it, the content must:',
    ...spec.fixes.map((fix) => `- ${fix}`),
  ];
  if (signal.page_url) {
    sections.push(
      '',
      `The page currently ranking for this query is ${signal.page_url}. Do not restate it — ` +
        'cover what it leaves unanswered.',
    );
  }
  return sections;
}

export function buildDemandBrief(
  signal: DemandSignal,
  project?: { brand_name?: string; website_url?: string } | null,
): DemandBrief {
  const spec = SIGNAL_SPECS[signal.signal_type] ?? FALLBACK;
  const target = signalTarget(signal);
  const isPageTarget = signalTargetKind(signal) === 'Page';

  const sections = isPageTarget
    ? pageBrief(signal, spec, target)
    : queryBrief(signal, spec, target);

  const measured = measuredLines(signal);
  if (measured.length > 0) {
    sections.push(
      '',
      isPageTarget
        ? 'Measured Search Console performance for this page:'
        : 'Measured Search Console performance for this query:',
      ...measured,
    );
  }
  sections.push(...competingLines(signal));

  if (project?.brand_name) {
    sections.push('', `Write on behalf of ${project.brand_name}.`);
  }
  if (signal.limitations.length > 0) {
    sections.push(
      '',
      `Caveats on this evidence: ${signal.limitations.join(' ')} Do not present any figure ` +
        'above as more precise than it is.',
    );
  }

  return {
    prompt: sections.join('\n'),
    suggestedSkillId: isPageTarget ? PAGE_SKILL : QUERY_SKILL,
    sourceLabel: `${spec.label} · ${target}`,
  };
}
