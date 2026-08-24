export const providerCatalogFixture = {
  transports: ['openai', 'anthropic', 'google'],
  engines: [
    {
      logical_engine: 'chatgpt',
      routes: [
        {
          measurement_mode: 'pulse',
          transport_provider: 'openai',
          transport_model: 'gpt-5.4-nano-2026-03-17',
          retrieval_enabled: false,
          reasoning_effort: 'off',
        },
        {
          measurement_mode: 'benchmark',
          transport_provider: 'openai',
          transport_model: 'gpt-5.6-sol',
          retrieval_enabled: true,
          reasoning_effort: 'off',
        },
      ],
    },
    {
      logical_engine: 'gemini',
      routes: [
        {
          measurement_mode: 'pulse',
          transport_provider: 'google',
          transport_model: 'gemini-3.5-flash-lite',
          retrieval_enabled: false,
          reasoning_effort: 'minimal',
        },
        {
          measurement_mode: 'benchmark',
          transport_provider: 'google',
          transport_model: 'gemini-3.6-flash',
          retrieval_enabled: true,
          reasoning_effort: 'low',
        },
      ],
    },
    {
      logical_engine: 'claude',
      routes: [
        {
          measurement_mode: 'pulse',
          transport_provider: 'anthropic',
          transport_model: 'claude-haiku-4-5-20251001',
          retrieval_enabled: false,
          reasoning_effort: 'off',
        },
        {
          measurement_mode: 'benchmark',
          transport_provider: 'anthropic',
          transport_model: 'claude-sonnet-5',
          retrieval_enabled: true,
          reasoning_effort: 'low',
        },
      ],
    },
  ],
};
