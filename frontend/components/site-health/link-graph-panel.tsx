'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { CursorPager } from '@/components/ui/cursor-pager';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { siteHealthQueries } from '@/lib/api/site-health';
import type { LinkGraphEdge, LinkGraphNode } from '@/lib/api/types';
import { useCursorStack } from '@/lib/site-health/use-cursor-stack';

const VISUAL_NODE_LIMIT = 24;

function displayPath(url: string) {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname}`;
  } catch {
    return url;
  }
}

function visualNodes(nodes: LinkGraphNode[]) {
  return [...nodes]
    .sort(
      (left, right) =>
        Number(right.near_orphan || right.weak_authority) -
          Number(left.near_orphan || left.weak_authority) ||
        right.pagerank - left.pagerank ||
        left.site_url_id.localeCompare(right.site_url_id),
    )
    .slice(0, VISUAL_NODE_LIMIT);
}

function GraphPreview({
  nodes,
  edges,
}: Readonly<{ nodes: LinkGraphNode[]; edges: LinkGraphEdge[] }>) {
  const visible = visualNodes(nodes);
  const positions = new Map(
    visible.map((node, index) => {
      const angle = (2 * Math.PI * index) / Math.max(visible.length, 1) - Math.PI / 2;
      return [node.site_url_id, { x: 260 + Math.cos(angle) * 190, y: 145 + Math.sin(angle) * 105 }];
    }),
  );
  const visibleEdges = edges.filter(
    (edge) =>
      edge.followed &&
      edge.target_site_url_id &&
      positions.has(edge.source_site_url_id) &&
      positions.has(edge.target_site_url_id),
  );

  if (visible.length < 2) return null;
  return (
    <div
      className="border-border bg-background-alt overflow-hidden rounded-lg border"
      aria-label="Internal link graph preview"
    >
      <svg viewBox="0 0 520 290" className="h-auto w-full" role="img">
        <title>Bounded preview of followed internal links</title>
        {visibleEdges.map((edge) => {
          const source = positions.get(edge.source_site_url_id)!;
          const target = positions.get(edge.target_site_url_id!)!;
          return (
            <line
              key={edge.id}
              x1={source.x}
              y1={source.y}
              x2={target.x}
              y2={target.y}
              className="stroke-border-strong"
              strokeWidth="1"
            />
          );
        })}
        {visible.map((node) => {
          const point = positions.get(node.site_url_id)!;
          const flagged = node.near_orphan || node.weak_authority;
          return (
            <g key={node.id}>
              <circle
                cx={point.x}
                cy={point.y}
                r={flagged ? 7 : node.hub ? 8 : 5}
                className={
                  flagged ? 'fill-warning-text' : node.hub ? 'fill-accent' : 'fill-secondary'
                }
              />
              <title>{displayPath(node.normalized_url)}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Signals({ node }: Readonly<{ node: LinkGraphNode }>) {
  return (
    <div className="flex flex-wrap gap-1">
      {node.near_orphan ? <Badge>Near orphan</Badge> : null}
      {node.weak_authority ? <Badge>Weak authority</Badge> : null}
      {node.hub ? <Badge>Hub</Badge> : null}
      {node.over_linked ? <Badge>Over-linked</Badge> : null}
      {!node.near_orphan && !node.weak_authority && !node.hub && !node.over_linked ? (
        <span className="text-subtle">—</span>
      ) : null}
    </div>
  );
}

export function LinkGraphPanel({
  projectId,
  crawlId,
}: Readonly<{ projectId: string; crawlId: string }>) {
  const nodePager = useCursorStack();
  const edgePager = useCursorStack();
  const summary = useQuery(siteHealthQueries.linkGraph(projectId, crawlId));
  const nodes = useQuery(siteHealthQueries.linkGraphNodes(projectId, crawlId, nodePager.cursor));
  const edges = useQuery(siteHealthQueries.linkGraphEdges(projectId, crawlId, edgePager.cursor));

  if (summary.isLoading || nodes.isLoading || edges.isLoading) {
    return (
      <p role="status" className="text-secondary text-sm">
        Loading persisted link evidence…
      </p>
    );
  }
  if (summary.isError || nodes.isError || edges.isError) {
    return <Alert tone="danger">Could not load the Website Link Graph.</Alert>;
  }
  if (!summary.data || summary.data.state === 'unavailable') {
    return (
      <Alert tone="info">
        A link graph will appear after a crawl has completed its graph analysis.
      </Alert>
    );
  }

  const nodeRows = nodes.data?.items ?? [];
  const edgeRows = edges.data?.items ?? [];
  const byId = new Map(nodeRows.map((node) => [node.site_url_id, node]));
  const coverage = summary.data.coverage;
  const observed = Number(coverage.analyzed_html_node_count ?? nodeRows.length);
  const selected = Number(coverage.selected_url_count ?? observed);

  return (
    <div className="grid min-w-0 gap-6" data-testid="website-link-graph">
      {summary.data.state === 'incomplete' ? (
        <Alert tone="warning">
          This is descriptive observed topology for a partial crawl ({observed} of {selected}{' '}
          selected HTML pages). Near-orphan and weak-authority Opportunities are suppressed.
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Internal-link authority</CardTitle>
          <CardDescription>
            Followed links form the topology. Nofollow observations remain in evidence but do not
            transfer authority.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <span className="text-subtle block">Pages</span>
              <span className="font-medium tabular-nums">
                {String(summary.data.summary.node_count ?? nodeRows.length)}
              </span>
            </div>
            <div>
              <span className="text-subtle block">Observed edges</span>
              <span className="font-medium tabular-nums">
                {String(summary.data.summary.edge_count ?? edgeRows.length)}
              </span>
            </div>
            <div>
              <span className="text-subtle block">Near orphans</span>
              <span className="font-medium tabular-nums">
                {String(summary.data.summary.near_orphan_count ?? 0)}
              </span>
            </div>
            <div>
              <span className="text-subtle block">Weak authority</span>
              <span className="font-medium tabular-nums">
                {String(summary.data.summary.weak_authority_count ?? 0)}
              </span>
            </div>
          </div>
          <GraphPreview nodes={nodeRows} edges={edgeRows} />
          {nodeRows.length > VISUAL_NODE_LIMIT ||
          nodes.data?.next_cursor ||
          edges.data?.next_cursor ? (
            <p className="text-subtle text-xs">
              The visual is bounded to {VISUAL_NODE_LIMIT} pages from the current evidence pages.
              The tables paginate through the persisted graph.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Page authority evidence</CardTitle>
          <CardDescription>
            Deterministic PageRank, click depth, followed links, and bounded source suggestions.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <div role="region" aria-label="Page authority evidence">
            <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Page</TableHead>
                <TableHead>Signals</TableHead>
                <TableHead numeric>In / out</TableHead>
                <TableHead>Suggested sources</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {nodeRows.map((node) => (
                <TableRow key={node.id}>
                  <TableCell>
                    <Link
                      className="text-accent-text font-medium hover:underline"
                      href={`/site/crawls/${crawlId}/pages/${node.site_url_id}`}
                    >
                      {node.title || displayPath(node.normalized_url)}
                    </Link>
                    <span className="text-subtle block max-w-80 truncate text-xs">
                      {displayPath(node.normalized_url)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Signals node={node} />
                  </TableCell>
                  <TableCell numeric>
                    {node.followed_inbound_count} / {node.followed_outbound_count}
                  </TableCell>
                  <TableCell>
                    {node.suggested_source_ids.length ? (
                      <div className="flex flex-wrap gap-x-2 gap-y-1">
                        {node.suggested_source_ids.map((sourceId) => {
                          const source = byId.get(sourceId);
                          return (
                            <Link
                              key={sourceId}
                              className="text-accent-text text-xs hover:underline"
                              href={`/site/crawls/${crawlId}/pages/${sourceId}`}
                            >
                              {source?.title || displayPath(source?.normalized_url ?? sourceId)}
                            </Link>
                          );
                        })}
                      </div>
                    ) : (
                      <span className="text-subtle">—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
            </Table>
          </div>
          {nodePager.canPrev || nodes.data?.next_cursor ? (
            <div className="mt-3 flex justify-end gap-2" aria-label="Page authority pagination">
              <CursorPager
                canPrev={nodePager.canPrev}
                canNext={Boolean(nodes.data?.next_cursor)}
                onPrev={nodePager.pop}
                onNext={() => nodePager.push(nodes.data?.next_cursor ?? null)}
              />
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Observed link evidence</CardTitle>
          <CardDescription>
            Collapsed followed and nofollow observations, with bounded anchor evidence.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <div role="region" aria-label="Observed link evidence">
            <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Source</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Transfer</TableHead>
                <TableHead numeric>Occurrences</TableHead>
                <TableHead>Anchors</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {edgeRows.map((edge) => {
                const source = byId.get(edge.source_site_url_id);
                const target = edge.target_site_url_id
                  ? byId.get(edge.target_site_url_id)
                  : undefined;
                return (
                  <TableRow key={edge.id}>
                    <TableCell>
                      {source?.title || displayPath(source?.normalized_url ?? edge.source_site_url_id)}
                    </TableCell>
                    <TableCell>
                      {target?.title || displayPath(target?.normalized_url ?? edge.target_url)}
                    </TableCell>
                    <TableCell>{edge.followed ? 'Followed' : 'Nofollow-only'}</TableCell>
                    <TableCell numeric>{edge.occurrence_count}</TableCell>
                    <TableCell>{edge.anchor_texts.join(', ') || '—'}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
            </Table>
          </div>
          {edgePager.canPrev || edges.data?.next_cursor ? (
            <div className="mt-3 flex justify-end gap-2" aria-label="Link evidence pagination">
              <CursorPager
                canPrev={edgePager.canPrev}
                canNext={Boolean(edges.data?.next_cursor)}
                onPrev={edgePager.pop}
                onNext={() => edgePager.push(edges.data?.next_cursor ?? null)}
              />
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
