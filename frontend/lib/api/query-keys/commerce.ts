/** Commerce (catalog feed health) query-key namespace. */
export const commerceKeys = {
  all: ['commerce'] as const,
  catalogHealth: (projectId: string) => ['commerce', 'catalog-health', projectId] as const,
};
