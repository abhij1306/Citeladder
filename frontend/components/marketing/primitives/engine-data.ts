export const ENGINES = {
  openai: { label: 'OpenAI', tile: 'bg-foreground' },
  claude: { label: 'Claude', tile: 'bg-brand-claude' },
  gemini: { label: 'Gemini', tile: 'bg-accent' },
} as const;

export type EngineKey = keyof typeof ENGINES;

/** The complete audited roster. One approved transport per engine. */
export const ENGINE_KEYS: readonly EngineKey[] = ['openai', 'gemini', 'claude'];
