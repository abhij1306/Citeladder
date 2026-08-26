'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input, Textarea } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { commerceApi } from '@/lib/api/commerce';
import { queryKeys } from '@/lib/api/query-keys';
import type { CommerceTarget } from '@/lib/api/schemas/commerce-suite';
import type { useCommerceQueries } from '@/lib/products/use-products-screen';

type Queries = ReturnType<typeof useCommerceQueries>;
const percentage = (value: number | null) =>
  value == null ? 'Unavailable' : `${(value * 100).toFixed(1)}%`;

export function CatalogPanel({
  projectId,
  query,
}: {
  projectId: string;
  query: Queries['catalog'];
}) {
  const client = useQueryClient();
  const [result, setResult] = useState('');
  const mutation = useMutation({
    mutationFn: async (file: File) =>
      commerceApi.importCatalog(projectId, await file.text(), file.name),
    onSuccess: async (data) => {
      setResult(
        `${data.created} created, ${data.updated} updated, ${data.unchanged} unchanged, ${data.rejected} rejected.`,
      );
      await client.invalidateQueries({ queryKey: queryKeys.commerce.catalog(projectId) });
    },
  });
  if (query.isLoading) return <p>Loading persisted catalog…</p>;
  if (query.isError || !query.data)
    return <Alert tone="danger">The catalog could not be loaded.</Alert>;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Canonical product catalog</CardTitle>
        <CardDescription>
          Site Health observations project automatically. CSV and explicit edits retain field-level
          authority.
        </CardDescription>
        <Input
          aria-label="Import catalog CSV"
          type="file"
          accept=".csv,text/csv"
          disabled={mutation.isPending}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) mutation.mutate(file);
          }}
        />
        {result ? <p className="text-secondary text-sm">{result}</p> : null}
        {mutation.isError ? <Alert tone="danger">The catalog import failed.</Alert> : null}
      </CardHeader>
      <CardContent>
        <p className="text-secondary mb-3 text-sm">
          {query.data.categories.length} categories · {query.data.products.length} products
        </p>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Product</TableHead>
              <TableHead>Brand</TableHead>
              <TableHead>Price</TableHead>
              <TableHead>Identity</TableHead>
              <TableHead>Sources</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data.products.map((product) => (
              <TableRow key={product.id}>
                <TableCell>
                  <a className="text-link" href={product.canonical_url}>
                    {product.name || product.canonical_url}
                  </a>
                </TableCell>
                <TableCell>{product.brand || 'Unknown'}</TableCell>
                <TableCell>
                  {product.price == null ? 'Unknown' : `${product.currency} ${product.price}`}
                </TableCell>
                <TableCell>{product.gtin || product.sku || product.mpn || 'URL'}</TableCell>
                <TableCell>{Object.keys(product.field_sources).length}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function TargetSelect({
  targets,
  value,
  onChange,
}: {
  targets: Array<{ label: string; target: CommerceTarget }>;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <select
      className="bg-input h-8 rounded-sm border px-2 text-sm"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {targets.map((item) => (
        <option
          key={`${item.target.kind}:${item.target.id}`}
          value={`${item.target.kind}:${item.target.id}`}
        >
          {item.label}
        </option>
      ))}
    </select>
  );
}

function availableTargets(query: Queries['catalog']) {
  if (!query.data) return [];
  return [
    ...query.data.categories.map((row) => ({
      label: row.name,
      target: { kind: 'category' as const, id: row.id },
    })),
    ...query.data.products.map((row) => ({
      label: row.name || row.canonical_url,
      target: { kind: 'product' as const, id: row.id },
    })),
  ];
}

export function CompetitorsPanel({ projectId, queries }: { projectId: string; queries: Queries }) {
  const client = useQueryClient();
  const targets = availableTargets(queries.catalog);
  const [selected, setSelected] = useState('');
  const current =
    targets.find((row) => `${row.target.kind}:${row.target.id}` === selected) ?? targets[0];
  const refresh = () =>
    client.invalidateQueries({ queryKey: queryKeys.commerce.competitors(projectId) });
  const discover = useMutation({
    mutationFn: () => commerceApi.discoverCompetitors(projectId, [current.target]),
    onSuccess: refresh,
  });
  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: 'approved' | 'rejected' }) =>
      commerceApi.decideCompetitor(projectId, id, decision),
    onSuccess: refresh,
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Competitor candidates</CardTitle>
        <CardDescription>
          Discovery is optional and evidence-backed. Candidates do not enter measurement until
          approved.
        </CardDescription>
        {current ? (
          <div className="flex gap-2">
            <TargetSelect
              targets={targets}
              value={`${current.target.kind}:${current.target.id}`}
              onChange={setSelected}
            />
            <Button onClick={() => discover.mutate()} disabled={discover.isPending}>
              Discover
            </Button>
          </div>
        ) : (
          <p>Project a catalog before discovering competitors.</p>
        )}
        {discover.isError || decide.isError ? (
          <Alert tone="danger">The competitor update failed. Please try again.</Alert>
        ) : null}
      </CardHeader>
      <CardContent>
        {queries.competitors.isError ? (
          <Alert tone="danger">Competitors could not be loaded.</Alert>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Candidate</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Decision</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(queries.competitors.data ?? []).map((row) => (
                <TableRow key={row.id}>
                  <TableCell>
                    <a className="text-link" href={row.canonical_url}>
                      {row.product_name || row.canonical_url}
                    </a>
                  </TableCell>
                  <TableCell>{row.target_kind}</TableCell>
                  <TableCell>{row.state}</TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        disabled={discover.isPending || decide.isPending}
                        onClick={() => decide.mutate({ id: row.id, decision: 'approved' })}
                      >
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={discover.isPending || decide.isPending}
                        onClick={() => decide.mutate({ id: row.id, decision: 'rejected' })}
                      >
                        Reject
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

export function BuyerPromptsPanel({ projectId, queries }: { projectId: string; queries: Queries }) {
  const client = useQueryClient();
  const targets = availableTargets(queries.catalog);
  const [selected, setSelected] = useState('');
  const [text, setText] = useState('');
  const current =
    targets.find((row) => `${row.target.kind}:${row.target.id}` === selected) ?? targets[0];
  const refresh = () =>
    client.invalidateQueries({ queryKey: queryKeys.commerce.buyerPrompts(projectId) });
  const manual = useMutation({
    mutationFn: () => commerceApi.addBuyerPrompt(projectId, current.target, text),
    onSuccess: async () => {
      setText('');
      await refresh();
    },
  });
  const generate = useMutation({
    mutationFn: () => commerceApi.generateBuyerPrompts(projectId, [current.target], 5),
    onSuccess: refresh,
  });
  const decide = useMutation({
    mutationFn: ({ id, approved }: { id: string; approved: boolean }) =>
      commerceApi.decideBuyerPrompt(projectId, id, approved),
    onSuccess: refresh,
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Buyer prompts</CardTitle>
        <CardDescription>
          Generated prompts are disabled until explicit approval. Manual entry remains available
          when no model is configured.
        </CardDescription>
        {current ? (
          <>
            <TargetSelect
              targets={targets}
              value={`${current.target.kind}:${current.target.id}`}
              onChange={setSelected}
            />
            <Textarea
              aria-label="Manual buyer prompt"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="What would a buyer ask?"
            />
            <div className="flex gap-2">
              <Button
                disabled={!text.trim() || manual.isPending || generate.isPending}
                onClick={() => manual.mutate()}
              >
                Add manually
              </Button>
              <Button
                variant="secondary"
                disabled={manual.isPending || generate.isPending}
                onClick={() => generate.mutate()}
              >
                Generate 5
              </Button>
            </div>
          </>
        ) : (
          <p>Project a catalog before creating buyer prompts.</p>
        )}
        {manual.isError || generate.isError || decide.isError ? (
          <Alert tone="danger">The buyer-prompt update failed. Please try again.</Alert>
        ) : null}
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Prompt</TableHead>
              <TableHead>Target</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Approval</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(queries.buyerPrompts.data ?? []).map((row) => (
              <TableRow key={row.id}>
                <TableCell>{row.text}</TableCell>
                <TableCell>{row.target.kind}</TableCell>
                <TableCell>{row.enabled ? 'Approved' : 'Draft'}</TableCell>
                <TableCell>
                  <Button
                    size="sm"
                    disabled={manual.isPending || generate.isPending || decide.isPending}
                    onClick={() => decide.mutate({ id: row.id, approved: !row.enabled })}
                  >
                    {row.enabled ? 'Disable' : 'Approve'}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

export function ShelfPanel({ query }: { query: Queries['shelf'] }) {
  if (query.isLoading) return <p>Loading persisted AI Shelf…</p>;
  if (query.isError || !query.data)
    return <Alert tone="danger">AI Shelf could not be loaded.</Alert>;
  const latest = query.data.snapshots[0];
  return (
    <div className="grid gap-4">
      <div className="grid gap-3 md:grid-cols-4">
        {[
          ['Product visibility', latest ? percentage(latest.product_visibility) : 'Unavailable'],
          ['Share of shelf', latest ? percentage(latest.share_of_shelf) : 'Unavailable'],
          ['Average shelf position', latest?.average_shelf_position?.toFixed(2) ?? 'Unavailable'],
          [
            'First-position win rate',
            latest ? percentage(latest.first_position_win_rate) : 'Unavailable',
          ],
        ].map(([label, value]) => (
          <Card key={label}>
            <CardHeader>
              <CardDescription>{label}</CardDescription>
              <CardTitle>{value}</CardTitle>
            </CardHeader>
          </Card>
        ))}
      </div>
      <Alert tone="info">
        Share of Shelf uses every recognized recommendation slot. Position metrics use only
        explicitly ordered recommendations, so these metrics can move differently.
      </Alert>
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
              {query.data.observations.map((row) => (
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
    </div>
  );
}
