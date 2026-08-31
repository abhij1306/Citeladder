'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { Trash2 } from 'lucide-react';
import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { BrandLogo } from '@/components/ui/brand-logo';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog } from '@/components/ui/dialog';
import { IntegrationSettings } from '@/components/settings/integration-settings';
import { BillingSettings } from '@/components/settings/billing-settings';
import { ProviderSettings } from '@/components/settings/provider-settings';
import { TabPanel, Tabs } from '@/components/ui/tabs';
import { projectsApi } from '@/lib/api/projects';
import { queryKeys } from '@/lib/api/query-keys';
import { useSessionUser } from '@/lib/auth/session-guard';
import { useProjectContext } from '@/lib/project/project-context';
import { emailInitials } from '@/lib/utils';
import { stringUrlCodec, useUrlState } from '@/lib/navigation/url-state';

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return 'Something went wrong. Please try again.';
}

/** Human-readable label for a timestamp (falls back to the raw value).
 * Explicit locale + UTC keep server and client output identical, so the
 * SSR markup matches during hydration. */
function formatTimestamp(timestamp: string | undefined): string | undefined {
  if (!timestamp) return undefined;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
  });
}

/** One read-only account detail row: label + value. */
function DetailRow({
  label,
  children,
  mono = false,
}: Readonly<{ label: string; children: React.ReactNode; mono?: boolean }>) {
  return (
    <div className="border-border-subtle grid min-h-12 grid-cols-[minmax(0,180px)_1fr] items-center gap-4 border-b py-2 last:border-b-0">
      <dt className="text-secondary text-sm font-medium">{label}</dt>
      <dd className={mono ? 'mono text-secondary text-xs' : 'text-foreground text-sm'}>
        {children}
      </dd>
    </div>
  );
}

const SETTINGS_TABS = [
  { id: 'account', label: 'Account' },
  { id: 'billing', label: 'Billing' },
  { id: 'providers', label: 'Providers' },
  { id: 'integrations', label: 'Integrations' },
  { id: 'danger', label: 'Danger zone' },
] as const;

type SettingsTab = (typeof SETTINGS_TABS)[number]['id'];

const SETTINGS_TAB_CODEC = stringUrlCodec(
  SETTINGS_TABS.map((tab) => tab.id),
  'account' as SettingsTab,
);

/**
 * SettingsScreen — tabbed settings (Account / Provider Settings / Integrations
 * / Danger Zone), following the WAI-ARIA tabs idiom used by the Visibility
 * workspace (roving tabindex, Arrow/Home/End navigation, `aria-selected`,
 * labelled panels).
 *
 * - **Account**: read-only session details from `GET /auth/me` via
 *   `useSessionUser` (no account-mutation endpoints exist) plus the
 *   appearance/theme control. `role` is the ACCOUNT-level role (free-form,
 *   defaults to `"user"`) and `created_at` is when the account was created —
 *   neither is a workspace membership role.
 * - **Provider Settings**: the BYOK provider configuration (formerly the
 *   settings-owned Providers tab), rendered by `ProviderSettings`.
 * - **Integrations**: first-party data connections (GSC/GA4 on one shared
 *   Google OAuth grant, Bing on a Microsoft grant), rendered by
 *   `IntegrationSettings`. `?tab=integrations` is the OAuth-callback landing
 *   surface (contract C2).
 * - **Danger Zone**: deletes the active project (backend cascades to all child
 *   data) behind a confirmation dialog — the one mutation on this screen.
 */
// react-doctor-disable-next-line react-doctor/no-giant-component -- this owns tab focus and project deletion state; billing, providers, integrations, and theme controls are extracted.
export function SettingsScreen() {
  const user = useSessionUser();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { activeProject, projects, setActiveProjectId } = useProjectContext();
  const createdLabel = formatTimestamp(user.created_at);
  const updatedLabel = formatTimestamp(user.updated_at);
  // Deep-linkable initial tab (`/settings?tab=providers` from the onboarding
  // card); invalid/absent values fall back to Account.
  const [activeTab, setActiveTab] = useUrlState('tab', SETTINGS_TAB_CODEC);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const deleteMutation = useMutation({
    mutationFn: (projectId: string) => projectsApi.deleteProject(projectId),
    onSuccess: async (_data, deletedId) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects.all });
      // Switch explicitly so the deleted project never flashes as "active"
      // while the context's useMemo re-resolves. Route to setup when the
      // workspace has no projects left.
      const next = projects.find((project) => project.id !== deletedId) ?? null;
      if (next) {
        setActiveProjectId(next.id);
        setConfirmOpen(false);
      } else {
        router.replace('/onboarding');
      }
    },
  });

  return (
    <div className="grid gap-[var(--workspace-gap)]">
      <Tabs
        value={activeTab}
        onValueChange={setActiveTab}
        items={SETTINGS_TABS.map((tab) => ({ value: tab.id, label: tab.label }))}
        ariaLabel="Settings sections"
        rootClassName="grid gap-6"
      >
        <TabPanel value="billing" forceMount className="focus-ring data-[state=inactive]:hidden">
          <BillingSettings enabled={activeTab === 'billing'} />
        </TabPanel>

        <TabPanel value="account" forceMount className="focus-ring data-[state=inactive]:hidden">
          {/* Two columns from lg, not a narrow centred rail. These cards are
            short, so a max-w-2xl column left most of a wide screen empty and
            pushed everything below the fold for no reason. */}
          <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
            <Card>
              <CardHeader>
                <CardTitle>Account</CardTitle>
                <CardDescription>Read-only — shown for reference.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-4">
                  <span
                    aria-hidden
                    className="bg-accent-soft text-accent-text flex size-10 shrink-0 items-center justify-center rounded-full text-sm font-medium uppercase"
                  >
                    {emailInitials(user.email)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-foreground truncate text-sm font-medium">{user.email}</div>
                    <div className="text-muted mt-0.5 text-sm capitalize">{user.role}</div>
                  </div>
                  <Badge variant="status" value={user.is_active ? 'success' : 'danger'}>
                    {user.is_active ? 'Active' : 'Inactive'}
                  </Badge>
                </div>

                {/* Only what the header above does NOT already state. Email, role
                  and status were each rendered twice — once in the identity row
                  and again as a detail row. */}
                <dl className="border-border-subtle mt-[var(--card-padding-large)] border-t">
                  {createdLabel ? (
                    <DetailRow label="Account created" mono>
                      {createdLabel}
                    </DetailRow>
                  ) : null}
                  {updatedLabel ? (
                    <DetailRow label="Last updated" mono>
                      {updatedLabel}
                    </DetailRow>
                  ) : null}
                  {user.id ? (
                    <DetailRow label="User ID" mono>
                      {user.id}
                    </DetailRow>
                  ) : null}
                </dl>
              </CardContent>
            </Card>
          </div>
        </TabPanel>

        <TabPanel value="providers" forceMount className="focus-ring data-[state=inactive]:hidden">
          <ProviderSettings />
        </TabPanel>

        <TabPanel
          value="integrations"
          forceMount
          className="focus-ring data-[state=inactive]:hidden"
        >
          <IntegrationSettings />
        </TabPanel>

        <TabPanel value="danger" forceMount className="focus-ring data-[state=inactive]:hidden">
          <div className="grid gap-4">
            <Card>
              <CardHeader>
                <CardTitle>Danger zone</CardTitle>
                <CardDescription>
                  Permanently delete the active project and everything inside it.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4">
                {activeProject ? (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <BrandLogo
                          name={activeProject.brand_name}
                          logoUrl={activeProject.brand?.logo_url}
                          websiteUrl={activeProject.website_url}
                          size="md"
                        />
                        <div className="min-w-0">
                          <div className="text-foreground truncate text-sm font-medium">
                            {activeProject.name}
                          </div>
                          <p className="text-muted mt-0.5 text-xs">
                            Brand: {activeProject.brand_name}
                          </p>
                        </div>
                      </div>
                      <Button
                        variant="destructive"
                        onClick={() => setConfirmOpen(true)}
                        disabled={deleteMutation.isPending}
                      >
                        <Trash2 className="size-4 shrink-0" aria-hidden strokeWidth={2} />
                        Delete project
                      </Button>
                    </div>
                    <Alert tone="danger">
                      Deleting a project removes all of its prompts, topics, audits, visibility
                      history, and generated content. This cannot be undone.
                    </Alert>
                    {deleteMutation.isError ? (
                      <Alert tone="danger">{errorMessage(deleteMutation.error)}</Alert>
                    ) : null}
                  </>
                ) : (
                  <p className="text-muted text-sm">No project selected.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </TabPanel>
      </Tabs>

      <Dialog
        open={confirmOpen}
        onOpenChange={(open) => {
          if (!deleteMutation.isPending) setConfirmOpen(open);
        }}
        title="Delete project"
        description={activeProject ? `Delete "${activeProject.name}"?` : undefined}
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setConfirmOpen(false)}
              disabled={deleteMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => activeProject && deleteMutation.mutate(activeProject.id)}
              disabled={deleteMutation.isPending || !activeProject}
            >
              {deleteMutation.isPending ? 'Deleting…' : 'Delete project'}
            </Button>
          </>
        }
      >
        <p className="text-secondary text-sm">
          This permanently deletes the project and all of its prompts, topics, audits, visibility
          history, and generated content. This cannot be undone.
        </p>
      </Dialog>
    </div>
  );
}
