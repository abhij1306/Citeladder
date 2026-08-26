/** Atomic Commerce suite query-key namespace. */
export const commerceKeys = {
  all: ['commerce'] as const,
  catalog: (projectId: string) => ['commerce', projectId, 'catalog'] as const,
  competitors: (projectId: string) => ['commerce', projectId, 'competitors'] as const,
  buyerPrompts: (projectId: string) => ['commerce', projectId, 'buyer-prompts'] as const,
  shelf: (projectId: string, auditId?: string) =>
    ['commerce', projectId, 'ai-shelf', auditId ?? 'latest'] as const,
};
