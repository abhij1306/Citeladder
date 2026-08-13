export const agentKeys = {
  all: ['agent'] as const,
  tasks: (projectId: string) => ['agent', 'tasks', projectId] as const,
  task: (projectId: string, runId: string) => ['agent', 'task', projectId, runId] as const,
};
