import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Label } from '@/components/ui/typography';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import type { PageDetail } from '@/lib/api/types';
import { PLACEHOLDER } from '@/lib/site-health/status';

/**
 * Internal links — the crawl's persisted link-graph projection for this page.
 *
 * Two numbers that look alike and are not: `Inbound` counts every internal
 * link, navigation included; `Main-content inbound` counts only the ones the
 * DOM placed inside the page's primary region. A page with a large first number
 * and a zero second one is in the menu and nowhere else. `Depth from home` is
 * shortest path over all followable links, because a nav link is a real click.
 *
 * The whole section is absent — not zeroed — when the crawl persisted no metric
 * for the URL, since "not measured" and "nothing links here" are different facts.
 */
export function InternalLinksCard({
  links,
  crawlId,
}: Readonly<{ links: PageDetail['internal_links']; crawlId: string }>) {
  if (links === null) return null;
  const metrics = [
    { label: 'Inbound', value: links.inbound_count },
    { label: 'Main-content inbound', value: links.main_content_inbound_count },
    { label: 'Outbound', value: links.outbound_count },
    { label: 'Main-content outbound', value: links.main_content_outbound_count },
    { label: 'Nofollow inbound', value: links.nofollow_inbound_count },
    {
      label: 'Depth from home',
      value: links.depth_from_home === null ? PLACEHOLDER : links.depth_from_home,
    },
  ];
  return (
    <Card className="min-w-0 overflow-hidden">
      <CardContent className="grid gap-4">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <h2 className="text-foreground text-base font-medium tracking-[-0.015em]">
            Internal Links
          </h2>
          <span className="text-muted shrink-0 text-xs">
            Counted across {links.source_page_count} crawled page
            {links.source_page_count === 1 ? '' : 's'}
          </span>
        </div>
        <dl className="grid gap-4 sm:grid-cols-3">
          {metrics.map((metric) => (
            <div key={metric.label} className="grid gap-0.5">
              <Label>{metric.label}</Label>
              <dd className="mono text-foreground text-sm font-medium">
                {metric.value === PLACEHOLDER ? (
                  <UnavailableValue state="not_measured" />
                ) : (
                  metric.value
                )}
              </dd>
            </div>
          ))}
        </dl>
        <div className="grid min-w-0 gap-4 sm:grid-cols-2">
          <NeighbourList
            heading="Top linking pages"
            neighbours={links.top_inbound}
            crawlId={crawlId}
            emptyMessage="No crawled page links here."
          />
          <NeighbourList
            heading="Top linked pages"
            neighbours={links.top_outbound}
            crawlId={crawlId}
            emptyMessage="This page links to no other crawled page."
          />
        </div>
      </CardContent>
    </Card>
  );
}

function NeighbourList({
  heading,
  neighbours,
  crawlId,
  emptyMessage,
}: Readonly<{
  heading: string;
  neighbours: NonNullable<PageDetail['internal_links']>['top_inbound'];
  crawlId: string;
  emptyMessage: string;
}>) {
  return (
    <section className="grid min-w-0 content-start gap-1.5 overflow-hidden">
      <Label>{heading}</Label>
      {neighbours.length === 0 ? (
        <p className="text-secondary text-sm">{emptyMessage}</p>
      ) : (
        <ul className="divide-border-subtle min-w-0 divide-y">
          {neighbours.map((neighbour) => (
            <li
              key={`${neighbour.site_url_id ?? neighbour.url}`}
              className="flex min-w-0 items-baseline justify-between gap-3 py-1.5 first:pt-0"
            >
              {/* An off-crawl target is counted but was never a node, so it has
                  no detail route to link to. */}
              {neighbour.site_url_id ? (
                <Link
                  href={`/site/crawls/${crawlId}/pages/${neighbour.site_url_id}`}
                  className="text-accent-text mono min-w-0 truncate text-xs hover:underline"
                  title={neighbour.url}
                >
                  {neighbour.url}
                </Link>
              ) : (
                <span
                  className="mono text-secondary min-w-0 truncate text-xs"
                  title={neighbour.url}
                >
                  {neighbour.url}
                </span>
              )}
              <span className="flex shrink-0 items-center gap-2">
                {neighbour.main_content ? <Badge>Main</Badge> : null}
                {neighbour.nofollow ? <Badge className="text-muted">nofollow</Badge> : null}
                <span className="mono text-muted text-xs">×{neighbour.anchor_count}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
