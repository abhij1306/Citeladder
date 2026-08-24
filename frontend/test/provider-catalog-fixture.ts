export const providerCatalogFixture = {
  transports: ['openai', 'anthropic', 'google'],
  engines: [
    {
      logical_engine: 'chatgpt',
      routes: [
        {
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
          transport_provider: 'anthropic',
          transport_model: 'claude-sonnet-5',
          retrieval_enabled: true,
          reasoning_effort: 'low',
        },
      ],
    },
  ],
};
