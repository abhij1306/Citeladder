import { Check, ChevronDown, Pencil, Plus, BookOpen } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { BrandProfilePanel } from '@/components/knowledge-base/brand-profile-panel';
import { CompetitorSuggestions } from '@/components/visibility/prompt-insights';
import { BrandLogo } from '@/components/ui/brand-logo';
import { Button } from '@/components/ui/button';
import { Drawer } from '@/components/ui/drawer';
import {
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownLabel,
  DropdownSeparator,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import { Alert } from '@/components/ui/alert';
import { projectsApi } from '@/lib/api/projects';
import { queryKeys } from '@/lib/api/query-keys';
import { visibilityApi } from '@/lib/api/visibility';
import type { Project } from '@/lib/api/types';

export function ProjectControls({
  projects,
  activeProject,
  activeProjectId,
  setActiveProjectId,
  onEditProject,
}: Readonly<{
  projects: Project[];
  activeProject: Project;
  activeProjectId?: string | null;
  setActiveProjectId: (projectId: string) => void;
  onEditProject?: (project: Project) => void;
}>) {
  const router = useRouter();
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <Button variant="secondary" size="sm" className="gap-1.5">
          Manage project <ChevronDown className="size-3.5 opacity-80" aria-hidden />
        </Button>
      </DropdownTrigger>
      <DropdownContent align="end" className="w-56">
        <DropdownLabel>Workspace brands</DropdownLabel>
        {projects.map((project) => (
          <DropdownItem key={project.id} onSelect={() => setActiveProjectId(project.id)}>
            <BrandLogo
              name={project.brand_name || project.name}
              logoUrl={project.brand?.logo_url}
              websiteUrl={project.website_url}
              size="sm"
            />
            <span className="min-w-0 flex-1 truncate font-medium">
              {project.brand_name || project.name}
            </span>
            {project.id === activeProjectId ? (
              <Check className="text-accent size-4" aria-hidden />
            ) : null}
          </DropdownItem>
        ))}
        <DropdownSeparator />
        {onEditProject ? (
          <DropdownItem onSelect={() => onEditProject(activeProject)}>
            <Pencil className="size-4" aria-hidden /> Edit active project
          </DropdownItem>
        ) : null}
        <DropdownItem onSelect={() => router.push('/onboarding?new=1')}>
          <Plus className="size-4" aria-hidden /> Add project
        </DropdownItem>
      </DropdownContent>
    </Dropdown>
  );
}

export function FactsDrawer({
  projectId,
  competitors,
}: Readonly<{ projectId: string; competitors: Project['competitors'] }>) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const profile = useQuery({
    queryKey: queryKeys.projects.brandProfile(projectId),
    queryFn: ({ signal }) => projectsApi.getBrandProfile(projectId, { signal }),
    enabled: open,
  });
  const suggestions = useQuery({
    queryKey: queryKeys.visibility.competitorSuggestions(projectId),
    queryFn: ({ signal }) => visibilityApi.listCompetitorSuggestions(projectId, { signal }),
    enabled: open,
  });
  return (
    <>
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)} className="gap-1.5">
        <BookOpen className="size-4" aria-hidden /> Edit facts
      </Button>
      <Drawer
        open={open}
        onOpenChange={setOpen}
        title="Company facts"
        description="Review the canonical facts and competitors used across CiteLadder."
        closeLabel="Close company facts"
      >
        <div className="flex flex-col gap-[var(--workspace-gap)]">
          {profile.isError ? <Alert tone="danger">Company facts could not be loaded.</Alert> : null}
          {profile.data ? (
            <BrandProfilePanel
              key={projectId}
              projectId={projectId}
              profile={profile.data}
              competitors={competitors}
              competitorSuggestions={
                <CompetitorSuggestions projectId={projectId} suggestionsQuery={suggestions} />
              }
              onSaved={() =>
                void queryClient.invalidateQueries({
                  queryKey: queryKeys.projects.commandCenter(projectId),
                })
              }
            />
          ) : null}
        </div>
      </Drawer>
    </>
  );
}
