'use client';

import { Check, ChevronsUpDown, Plus } from 'lucide-react';
import { useRouter } from 'next/navigation';

import {
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownLabel,
  DropdownSeparator,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import { BrandLogo } from '@/components/ui/brand-logo';
import { useProjectContext } from '@/lib/project/project-context';
import { cn } from '@/lib/utils';

/**
 * ProjectSwitcher (F5) — brand avatar + active project name with a dropdown of
 * all projects in the workspace. Selecting one updates the project context
 * (which persists the choice and re-scopes the API client's workspace header).
 */
export function ProjectSwitcher({ className }: Readonly<{ className?: string }>) {
  const router = useRouter();
  const { projects, activeProject, activeProjectId, setActiveProjectId, isLoading } =
    useProjectContext();

  const label = activeProject?.brand_name ?? activeProject?.name ?? 'No project';

  return (
    <Dropdown>
      <DropdownTrigger
        className={cn(
          'focus-ring hover:bg-background-alt flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left transition-colors disabled:pointer-events-none disabled:opacity-50',
          className,
        )}
        disabled={isLoading}
      >
        <BrandLogo
          name={label}
          logoUrl={activeProject?.brand.logo_url}
          websiteUrl={activeProject?.website_url}
          size="sm"
          className="bg-foreground text-background size-6.5 rounded-sm"
        />
        <span className="text-foreground min-w-0 flex-1 truncate text-sm font-medium tracking-tight">
          {label}
        </span>
        <ChevronsUpDown className="text-muted size-3.5 shrink-0" aria-hidden strokeWidth={2} />
      </DropdownTrigger>
      <DropdownContent align="start" className="w-56">
        <DropdownLabel>Projects</DropdownLabel>
        <DropdownSeparator className="bg-border-subtle my-1 h-px" />
        {projects.map((project) => {
          const selected = project.id === activeProjectId;
          return (
            <DropdownItem
              key={project.id}
              data-active={selected}
              onSelect={() => setActiveProjectId(project.id)}
            >
              <BrandLogo
                name={project.brand_name || project.name}
                logoUrl={project.brand.logo_url}
                websiteUrl={project.website_url}
                size="sm"
              />
              <span className="min-w-0 flex-1 truncate">{project.brand_name || project.name}</span>
              {selected ? <Check className="text-accent size-4 shrink-0" aria-hidden /> : null}
            </DropdownItem>
          );
        })}
        <DropdownSeparator className="bg-border-subtle my-1 h-px" />
        <DropdownItem onSelect={() => router.push('/onboarding?new=1')}>
          <span
            aria-hidden
            className="bg-accent-soft text-accent-text flex size-6 shrink-0 items-center justify-center rounded-sm"
          >
            <Plus className="size-4" />
          </span>
          <span className="min-w-0 flex-1 truncate">New project</span>
        </DropdownItem>
      </DropdownContent>
    </Dropdown>
  );
}
