'use client';

import { SiteHealthScreen } from '@/components/site-health/site-health-screen';
import { AgentLauncher } from '@/components/layout/agent-sheet';
import { TooltipProvider } from '@/components/ui/tooltip';

/** Canonical Website surface backed by the retained Site Health capability. */
export default function SitePage() {
  return (
    <TooltipProvider>
      <div className="flex flex-col gap-6">
        <SiteHealthScreen />
        <AgentLauncher
          taskType="build_roadmap"
          objective="Build a roadmap from the current Website evidence."
          className="text-accent-text self-start text-sm font-medium underline-offset-2 hover:underline"
        >
          Build a roadmap with the Growth Agent
        </AgentLauncher>
      </div>
    </TooltipProvider>
  );
}
