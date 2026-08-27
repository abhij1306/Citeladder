'use client';

import { Alert } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { CommerceTarget } from '@/lib/api/schemas/commerce-suite';

import { TargetSelect, availableTargets, type CommerceQueries } from './commerce-panels';

const percentage = (value: number | null) =>
  value == null ? 'Unavailable' : `${(value * 100).toFixed(1)}%`;

export function ShelfPanel({
  queries,
  target,
  onTargetChange,
}: {
  queries: CommerceQueries;
  target?: CommerceTarget;
  onTargetChange: (target: CommerceTarget) => void;
}) {
  const targets = availableTargets(queries.catalog);
  const selectedValue = target ? `${target.kind}:${target.id}` : '';
  const selectTarget = (value: string) => {
    const selected = targets.find((row) => `${row.target.kind}:${row.target.id}` === value);
    if (selected) onTargetChange(selected.target);
  };
  if (queries.catalog.isLoading) return <p>Loading Commerce targets…</p>;
  if (queries.catalog.isError)
    return <Alert tone="danger">Commerce targets could not be loaded.</Alert>;
  if (!target) {
    return <ShelfTargetPrompt targets={targets} onChange={selectTarget} />;
  }
  return (
    <ShelfResults
      query={queries.shelf}
      targets={targets}
      selectedValue={selectedValue}
      selectTarget={selectTarget}
    />
  );
}

function ShelfTargetPrompt({
  targets,
  onChange,
}: {
  targets: ReturnType<typeof availableTargets>;
  onChange: (value: string) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>AI Shelf target</CardTitle>
        <CardDescription>
          Select one product or category to load its metrics, evidence, and history.
        </CardDescription>
        {targets.length ? (
          <TargetSelect
            label="AI Shelf target"
            targets={targets}
            value=""
            onChange={onChange}
            placeholder="Select a product or category"
          />
        ) : (
          <p>Project a catalog before viewing AI Shelf.</p>
        )}
      </CardHeader>
    </Card>
  );
}

function ShelfResults({
  query,
  targets,
  selectedValue,
  selectTarget,
}: {
  query: CommerceQueries['shelf'];
  targets: ReturnType<typeof availableTargets>;
  selectedValue: string;
  selectTarget: (value: string) => void;
}) {
  if (query.isLoading) return <p>Loading persisted AI Shelf…</p>;
  if (query.isError || !query.data)
    return <Alert tone="danger">AI Shelf could not be loaded.</Alert>;
  const latest = query.data.snapshots[0];
  return (
    <div className="grid gap-4">
      <TargetSelect
        label="AI Shelf target"
        targets={targets}
        value={selectedValue}
        onChange={selectTarget}
      />
      <ShelfMetrics latest={latest} />
      <Alert tone="info">
        Share of Shelf uses every recognized recommendation slot. Position metrics use only
        explicitly ordered recommendations, so these metrics can move differently.
      </Alert>
      <RecommendationEvidence observations={query.data.observations} />
      <ShelfHistory snapshots={query.data.snapshots} />
    </div>
  );
}

function ShelfMetrics({
  latest,
}: {
  latest: NonNullable<CommerceQueries['shelf']['data']>['snapshots'][number] | undefined;
}) {
  const metrics = [
    ['Product visibility', latest ? percentage(latest.product_visibility) : 'Unavailable'],
    ['Share of shelf', latest ? percentage(latest.share_of_shelf) : 'Unavailable'],
    ['Average shelf position', latest?.average_shelf_position?.toFixed(2) ?? 'Unavailable'],
    [
      'First-position win rate',
      latest ? percentage(latest.first_position_win_rate) : 'Unavailable',
    ],
  ];
  return (
    <div className="grid gap-3 md:grid-cols-4">
      {metrics.map(([label, value]) => (
        <Card key={label}>
          <CardHeader>
            <CardDescription>{label}</CardDescription>
            <CardTitle>{value}</CardTitle>
          </CardHeader>
        </Card>
      ))}
    </div>
  );
}

function RecommendationEvidence({
  observations,
}: {
  observations: NonNullable<CommerceQueries['shelf']['data']>['observations'];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recommendation evidence</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Observed product</TableHead>
              <TableHead>Class</TableHead>
              <TableHead>Merchant</TableHead>
              <TableHead>Rank</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {observations.map((row) => (
              <TableRow key={row.id}>
                <TableCell>{row.observed_product || row.observed_title}</TableCell>
                <TableCell>{row.classification}</TableCell>
                <TableCell>{row.merchant_domain || 'Not observed'}</TableCell>
                <TableCell>{row.order_observable ? row.rank : 'Unordered'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function ShelfHistory({
  snapshots,
}: {
  snapshots: NonNullable<CommerceQueries['shelf']['data']>['snapshots'];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Measurement history</CardTitle>
        <CardDescription>Immutable snapshots for the selected target.</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Measured</TableHead>
              <TableHead>Visibility</TableHead>
              <TableHead>Share of shelf</TableHead>
              <TableHead>Average position</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {snapshots.map((snapshot) => (
              <TableRow key={snapshot.id}>
                <TableCell>{new Date(snapshot.created_at).toLocaleString()}</TableCell>
                <TableCell>{percentage(snapshot.product_visibility)}</TableCell>
                <TableCell>{percentage(snapshot.share_of_shelf)}</TableCell>
                <TableCell>
                  {snapshot.average_shelf_position?.toFixed(2) ?? 'Unavailable'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
