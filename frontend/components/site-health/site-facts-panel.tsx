'use client';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Label } from '@/components/ui/typography';
import type { SiteCrawl, SiteHealthDashboard } from '@/lib/api/types';
import {
  AI_CRAWLER_ENGINE_LABELS,
  readSiteFacts,
  type AiCrawlerBot,
  type SiteFactsStance,
  type SiteFactsView,
} from '@/lib/site-health/site-facts';
import { cn } from '@/lib/utils';

function engineLabel(bot: string): string {
  return AI_CRAWLER_ENGINE_LABELS[bot as AiCrawlerBot] ?? bot;
}

/** One bot's Allow/Block/Unknown chip — left-aligned inside its grid cell. */
function StanceBadge({ stance }: Readonly<{ stance: SiteFactsStance }>) {
  if (stance === 'allow') {
    return (
      <Badge variant="status" value="success" className="justify-self-start">
        Allow
      </Badge>
    );
  }
  if (stance === 'block') {
    return (
      <Badge variant="status" value="danger" className="justify-self-start">
        Block
      </Badge>
    );
  }
  return <Badge className="justify-self-start">Unknown</Badge>;
}

/** Header summary chip: blocked count, unknown stance, or all-allowed. */
function SummaryBadge({ view }: Readonly<{ view: SiteFactsView }>) {
  // B2: only a FETCH FAILURE leaves the stance genuinely unknown — a 404
  // means "no robots.txt", which is a definitive all-allowed, not an unknown.
  if (view.robotsFetchStatus === 'fetch_failed') {
    return (
      <Badge variant="status" value="warning">
        Stance unknown
      </Badge>
    );
  }
  const blockedCount = view.bots.filter((bot) => bot.stance === 'block').length;
  if (blockedCount > 0) {
    return (
      <Badge variant="status" value="danger">
        {blockedCount} of {view.bots.length} blocked
      </Badge>
    );
  }
  return (
    <Badge variant="status" value="success">
      All {view.bots.length} allowed
    </Badge>
  );
}

/** Mono status code for one well-known file, `—` when no fetch answered. */
function StatusValue({ status }: Readonly<{ status: number | null }>) {
  if (status === null) {
    return <span className="mono text-muted text-sm font-medium">—</span>;
  }
  return <span className="mono text-foreground text-sm font-medium">{status}</span>;
}

/**
 * Dashboard "AI crawler access" panel (site-health v2 P2).
 *
 * Renders the crawl's bounded `site_facts` blob: the robots.txt AI-crawler
 * stance strip (one cell per known AI bot), a blocked/unknown-stance alert,
 * and the well-known file row (robots.txt + llms.txt status and the checked
 * URLs). Never Free-redacted, so no entitlement gating. Follows the same
 * dashboard-then-crawl fallback as the page-kind scores; renders NOTHING
 * while no completed crawl has persisted `site_facts` yet (the absent
 * mockup omits the panel entirely).
 */
export function SiteFactsPanel({
  crawl,
  dashboard,
}: Readonly<{
  crawl: SiteCrawl | null;
  dashboard: SiteHealthDashboard | undefined;
}>) {
  const view = readSiteFacts(dashboard?.crawl?.site_facts ?? crawl?.site_facts);
  if (view === null) return null;

  const blocked = view.bots.filter((bot) => bot.stance === 'block');

  return (
    <Card data-testid="site-facts-panel">
      <CardContent className="grid gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid gap-0.5">
            <Label>AI crawler access</Label>
            <span className="text-secondary text-sm">
              Which AI answer engines your robots.txt allows to crawl this site.
            </span>
          </div>
          <SummaryBadge view={view} />
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="site-facts-stance-grid">
          {view.bots.map(({ bot, stance }) => (
            <div
              key={bot}
              data-testid={`site-facts-stance-${bot.toLowerCase()}`}
              className={cn(
                'grid gap-2 rounded-md border px-3 py-2',
                stance === 'block'
                  ? 'border-danger-border bg-danger-bg'
                  : 'border-border-subtle bg-background-alt',
              )}
            >
              <span className="mono text-foreground truncate text-sm font-medium">{bot}</span>
              <StanceBadge stance={stance} />
              <span className="text-2xs text-muted">{engineLabel(bot)}</span>
            </div>
          ))}
        </div>

        {view.robotsFetched && blocked.length === 1 ? (
          <Alert tone="danger">
            {blocked[0].bot} is disallowed in robots.txt — {engineLabel(blocked[0].bot)} cannot
            crawl these pages, so they can never be cited in its answers.
          </Alert>
        ) : null}
        {view.robotsFetched && blocked.length > 1 ? (
          <Alert tone="danger">
            {blocked.map(({ bot }) => bot).join(', ')} are disallowed in robots.txt — those answer
            engines cannot crawl these pages, so they can never cite them.
          </Alert>
        ) : null}
        {view.robotsFetchStatus === 'not_found' ? (
          <Alert tone="info">
            No robots.txt — crawling proceeds fail-open; the AI-crawler stance defaults to allow.
          </Alert>
        ) : null}
        {view.robotsFetchStatus === 'fetch_failed' ? (
          <Alert tone="warning">
            robots.txt could not be fetched, so the AI-crawler stance could not be read. Crawling
            continued with the fail-open default.
          </Alert>
        ) : null}

        <div
          className="border-border-subtle flex flex-wrap items-start gap-x-8 gap-y-3 border-t pt-3"
          data-testid="site-facts-well-known-files"
        >
          <div className="grid gap-0.5">
            <Label>robots.txt</Label>
            <span className="flex items-center gap-2">
              <StatusValue status={view.robotsStatus} />
              {view.robotsFetchStatus === 'fetched' ? (
                <Badge variant="status" value="success">
                  Fetched
                </Badge>
              ) : view.robotsFetchStatus === 'not_found' ? (
                <Badge>Not found</Badge>
              ) : (
                <Badge variant="status" value="warning">
                  Not fetched
                </Badge>
              )}
            </span>
          </div>
          <div className="grid gap-0.5">
            <Label>llms.txt</Label>
            <span className="flex items-center gap-2">
              <StatusValue status={view.llmsTxtStatus} />
              {!view.llmsTxtFetched ? (
                <Badge variant="status" value="warning">
                  Not fetched
                </Badge>
              ) : view.llmsTxtPresent ? (
                <Badge variant="status" value="success">
                  Present
                </Badge>
              ) : (
                <Badge variant="status" value="warning">
                  Absent
                </Badge>
              )}
            </span>
          </div>
          <div className="ms-auto grid gap-0.5">
            <Label>Checked</Label>
            <span className="mono text-muted text-sm font-medium">{view.robotsUrl ?? '—'}</span>
            {view.llmsTxtUrl !== null ? (
              <span className="mono text-muted text-sm font-medium">{view.llmsTxtUrl}</span>
            ) : null}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
