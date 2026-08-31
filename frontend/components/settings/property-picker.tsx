'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Loader2 } from 'lucide-react';
import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { Pressable } from '@/components/ui/pressable';
import {
  integrationsApi,
  type IntegrationConnection,
  type IntegrationProperty,
} from '@/lib/api/integrations';
import { queryKeys } from '@/lib/api/query-keys';
import { useProjectContext } from '@/lib/project/project-context';
import { cn } from '@/lib/utils';

const PROVIDER_NOUN: Record<IntegrationConnection['provider'], string> = {
  gsc: 'Search Console property',
  ga4: 'Analytics property',
  bing: 'Bing site',
};

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return 'Something went wrong. Please try again.';
}

/**
 * One selectable row in the picker list.
 *
 * A button rather than a radio: selecting IS the commit here (there is no
 * separate confirm step), so the row must read as an action.
 */
function PropertyOption({
  property,
  selected,
  disabled,
  pending,
  onSelect,
}: Readonly<{
  property: IntegrationProperty;
  selected: boolean;
  disabled: boolean;
  pending: boolean;
  onSelect: () => void;
}>) {
  return (
    <Pressable
      type="button"
      onClick={onSelect}
      disabled={disabled}
      aria-pressed={selected}
      className={cn(
        'border-border-subtle flex w-full items-center gap-3 rounded-md border px-3 py-2 text-start',
        'hover:bg-well focus-visible:ring-accent focus-visible:ring-2 focus-visible:outline-none',
        'disabled:pointer-events-none disabled:opacity-60',
        selected && 'border-accent bg-well',
      )}
    >
      <span className="min-w-0 flex-1">
        <span className="text-foreground block truncate text-sm font-medium">{property.label}</span>
        <span className="text-muted block truncate font-mono text-xs">{property.property_ref}</span>
      </span>
      {pending ? <Loader2 className="text-muted size-4 shrink-0 animate-spin" aria-hidden /> : null}
      {selected && !pending ? <Check className="text-accent size-4 shrink-0" aria-hidden /> : null}
    </Pressable>
  );
}

/**
 * Property picker for one integration connection.
 *
 * A connected OAuth grant does not by itself tell a sync WHAT to pull: the
 * worker fetches from the connection's `account_ref`, and derivation resolves
 * that ref back to a project through an active property mapping. Selecting
 * here creates that mapping against the ACTIVE project, which is also what
 * points `account_ref` at the property — so an unselected connection syncs
 * nothing and says so, rather than failing against an empty property id.
 *
 * Options come from the provider itself (`GET …/properties`), never free
 * text, so a ref can't be typed wrong. That call is live and lazy: it runs
 * only once the dialog opens.
 */
/**
 * The connection's ACTIVE property mapping, or `null`.
 *
 * The mapping — not `connection.account_ref` — is what decides whether a sync
 * produces anything: the worker fetches from `account_ref`, but derivation
 * then has to resolve that ref back to a project through an active mapping,
 * and a run whose mapping is missing fails `unmapped_property` after the
 * fetch. The two drift apart for real: mappings cascade away when their
 * project is deleted, while `account_ref` lives on the connection and
 * survives. Reading `account_ref` alone therefore renders a confidently
 * "selected" property whose every sync is failing.
 *
 * Shared with `integration-card` so the row's Sync button and the picker
 * agree; react-query dedupes the two subscribers onto one request.
 */
export function useActiveMapping(connectionId: string) {
  const query = useQuery({
    queryKey: queryKeys.integrations.mappings(connectionId),
    queryFn: ({ signal }) => integrationsApi.listMappings(connectionId, { signal }),
    staleTime: 60 * 1000,
  });
  return query.data?.find((mapping) => mapping.status === 'active') ?? null;
}

export function PropertyPicker({
  connection,
  disabled = false,
}: Readonly<{ connection: IntegrationConnection; disabled?: boolean }>) {
  const queryClient = useQueryClient();
  const { activeProject } = useProjectContext();
  const activeMapping = useActiveMapping(connection.id);
  const [open, setOpen] = useState(false);
  const [pendingRef, setPendingRef] = useState<string | null>(null);

  const propertiesQuery = useQuery({
    queryKey: queryKeys.integrations.properties(connection.id),
    queryFn: ({ signal }) => integrationsApi.listProperties(connection.id, { signal }),
    // Live provider call — only fetch once the picker is actually open.
    enabled: open,
    // Property lists barely change; don't re-hit Google on every reopen.
    staleTime: 5 * 60 * 1000,
  });

  const selectMutation = useMutation({
    mutationFn: (propertyRef: string) => {
      if (!activeProject) throw new Error('Select a project first.');
      return integrationsApi.createMapping(connection.id, {
        provider: connection.provider,
        property_ref: propertyRef,
        project_id: activeProject.id,
      });
    },
    onSuccess: async () => {
      setOpen(false);
      setPendingRef(null);
      // account_ref moved with the mapping — refresh the connection list.
      await queryClient.invalidateQueries({ queryKey: queryKeys.integrations.all });
    },
    onError: () => setPendingRef(null),
  });

  // The active mapping, never the connection's account_ref — see
  // `useActiveMapping`. A stale account_ref would show a property as chosen
  // while every sync of it fails.
  const selected = activeMapping?.property_ref ?? '';
  const noun = PROVIDER_NOUN[connection.provider];

  return (
    <>
      <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
        {selected ? (
          <span className="bg-well border-border-subtle text-secondary max-w-full truncate rounded border px-2 py-0.5 font-mono text-xs">
            {selected}
          </span>
        ) : (
          <span className="text-warning-text bg-warning-bg/50 max-w-full truncate rounded px-2 py-0.5 text-xs font-medium">
            No {noun} selected
          </span>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-1.5 text-xs"
          onClick={() => setOpen(true)}
          disabled={disabled}
          data-testid={`select-property-${connection.provider}`}
        >
          {selected ? 'Change' : 'Select'}
        </Button>
      </div>

      <Dialog
        open={open}
        // Hold the dialog open while a selection is in flight, matching the
        // sibling confirm dialog: dismissing mid-mutation would unmount the
        // only surface showing the pending row and any resulting error.
        onOpenChange={(next) => {
          if (!selectMutation.isPending) setOpen(next);
        }}
        title={`Choose a ${noun}`}
        description={
          activeProject
            ? `Data for the selected property is imported into ${activeProject.name}.`
            : 'Select a project before choosing a property.'
        }
      >
        <div className="grid gap-2 py-3">
          {!activeProject ? (
            <Alert tone="warning">
              No active project. Create or select a project first — a property must be imported into
              one.
            </Alert>
          ) : null}

          {propertiesQuery.isLoading ? (
            <>
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </>
          ) : null}

          {propertiesQuery.isError ? (
            <Alert tone="danger">
              Could not load your properties from the provider.{' '}
              {errorMessage(propertiesQuery.error)}
            </Alert>
          ) : null}

          {propertiesQuery.data?.length === 0 ? (
            <Alert tone="neutral">
              This account has no {noun} available. Verify the property in the provider&rsquo;s own
              console first, then reopen this dialog.
            </Alert>
          ) : null}

          {propertiesQuery.data?.map((property) => (
            <PropertyOption
              key={property.property_ref}
              property={property}
              selected={property.property_ref === selected}
              disabled={!activeProject || selectMutation.isPending}
              pending={pendingRef === property.property_ref}
              onSelect={() => {
                setPendingRef(property.property_ref);
                selectMutation.mutate(property.property_ref);
              }}
            />
          ))}

          {selectMutation.isError ? (
            <Alert tone="danger">{errorMessage(selectMutation.error)}</Alert>
          ) : null}
        </div>
      </Dialog>
    </>
  );
}
