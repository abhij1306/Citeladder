'use client';

import { Bot } from 'lucide-react';
import { usePathname, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import {
  GrowthAgentWorkspace,
  type AgentRouteContext,
} from '@/components/agent/growth-agent-workspace';
import { Button } from '@/components/ui/button';
import { Drawer } from '@/components/ui/drawer';
import type { AgentTaskType } from '@/lib/api/agent';
import { useProjectContext } from '@/lib/project/project-context';

const OPEN_AGENT_EVENT = 'citeladder:open-agent';
const DATE_KEYS = new Set(['start', 'end', 'start_date', 'end_date', 'date_from', 'date_to']);

type AgentLaunch = { taskType: AgentTaskType; objective: string };

function boundedFilters(search: URLSearchParams): Readonly<Record<string, readonly string[]>> {
  const filters: Record<string, string[]> = {};
  for (const key of [...new Set(search.keys())]
    .sort((left, right) => left.localeCompare(right))
    .slice(0, 10)) {
    if (DATE_KEYS.has(key)) continue;
    filters[key] = search.getAll(key).slice(0, 10).map((value) => value.slice(0, 200));
  }
  return filters;
}

function dateRange(search: URLSearchParams): AgentRouteContext['dateRange'] {
  const start = search.get('start') ?? search.get('start_date') ?? search.get('date_from');
  const end = search.get('end') ?? search.get('end_date') ?? search.get('date_to');
  return start && end ? { start, end } : null;
}

export function AgentLauncher({
  taskType = 'explain',
  objective = '',
  children,
  className,
}: Readonly<{
  taskType?: AgentTaskType;
  objective?: string;
  children: ReactNode;
  className?: string;
}>) {
  return (
    <button
      type="button"
      className={className}
      onClick={() =>
        window.dispatchEvent(
          new CustomEvent<AgentLaunch>(OPEN_AGENT_EVENT, { detail: { taskType, objective } }),
        )
      }
    >
      {children}
    </button>
  );
}

export function AgentSheet() {
  const pathname = usePathname() ?? '/projects';
  const searchParams = useSearchParams();
  const { activeProject } = useProjectContext();
  const [open, setOpen] = useState(false);
  const [launch, setLaunch] = useState<AgentLaunch>({ taskType: 'explain', objective: '' });
  const previousProjectId = useRef(activeProject?.id ?? null);

  useEffect(() => {
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<AgentLaunch>).detail;
      setLaunch(detail);
      setOpen(true);
    };
    window.addEventListener(OPEN_AGENT_EVENT, listener);
    return () => window.removeEventListener(OPEN_AGENT_EVENT, listener);
  }, []);

  useEffect(() => {
    const projectId = activeProject?.id ?? null;
    if (previousProjectId.current !== projectId) {
      setOpen(false);
      setLaunch({ taskType: 'explain', objective: '' });
      previousProjectId.current = projectId;
    }
  }, [activeProject?.id]);

  const routeContext = useMemo<AgentRouteContext | undefined>(() => {
    if (!activeProject) return undefined;
    return {
      workspaceId: activeProject.workspace_id,
      projectId: activeProject.id,
      canonicalRoute: pathname,
      dateRange: dateRange(searchParams),
      filters: boundedFilters(searchParams),
    };
  }, [activeProject, pathname, searchParams]);

  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)} className="gap-1.5">
        <Bot className="size-4" aria-hidden />
        <span className="hidden sm:inline">Agent</span>
      </Button>
      <Drawer
        open={open}
        onOpenChange={setOpen}
        title="Growth Agent"
        description="Explain saved evidence or prioritize the next action."
        closeLabel="Close Growth Agent"
        bodyClassName="p-0"
      >
        <GrowthAgentWorkspace
          key={`${activeProject?.id ?? 'none'}:${launch.taskType}:${launch.objective}`}
          initialTask={launch.taskType}
          initialObjective={launch.objective}
          routeContext={routeContext}
        />
      </Drawer>
    </>
  );
}
