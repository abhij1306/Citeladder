import { Suspense } from 'react';

import { GrowthAgentWorkspace } from '@/components/agent/growth-agent-workspace';

export default function AgentPage() {
  return (
    <Suspense fallback={<p className="text-muted text-sm">Loading Growth Agent…</p>}>
      <GrowthAgentWorkspace />
    </Suspense>
  );
}
