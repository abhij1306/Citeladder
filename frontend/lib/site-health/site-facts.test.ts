import { describe, expect, it } from 'vitest';

import { AI_CRAWLER_BOTS, AI_CRAWLER_ENGINE_LABELS, readSiteFacts } from './site-facts';

/** Bounded blob the worker persists (`_crawl_setup`); variant A — GPTBot blocked. */
const variantA = {
  robots: {
    fetched: true,
    status: 'fetched',
    url: 'https://acme.com/robots.txt',
    status_code: 200,
    ai_crawlers: {
      GPTBot: 'block',
      ClaudeBot: 'allow',
      PerplexityBot: 'allow',
      'Google-Extended': 'allow',
    },
    sitemaps: ['https://acme.com/sitemap.xml'],
  },
  llms_txt: { fetched: true, url: 'https://acme.com/llms.txt', status_code: 200, present: true },
  sitemap: { fetched: true, files: ['https://acme.com/sitemap.xml'] },
};

/** Variant B — every bot allowed. */
const variantB = {
  ...variantA,
  robots: {
    ...variantA.robots,
    ai_crawlers: {
      GPTBot: 'allow',
      ClaudeBot: 'allow',
      PerplexityBot: 'allow',
      'Google-Extended': 'allow',
    },
  },
};

describe('readSiteFacts', () => {
  it('parses variant A (GPTBot blocked, others allow) in canonical bot order', () => {
    const view = readSiteFacts(variantA);
    expect(view).not.toBeNull();
    expect(view?.robotsFetched).toBe(true);
    expect(view?.robotsStatus).toBe(200);
    expect(view?.robotsUrl).toBe('https://acme.com/robots.txt');
    expect(view?.bots).toEqual([
      { bot: 'GPTBot', stance: 'block' },
      { bot: 'ClaudeBot', stance: 'allow' },
      { bot: 'PerplexityBot', stance: 'allow' },
      { bot: 'Google-Extended', stance: 'allow' },
    ]);
    expect(view?.llmsTxtFetched).toBe(true);
    expect(view?.llmsTxtPresent).toBe(true);
    expect(view?.llmsTxtStatus).toBe(200);
    expect(view?.llmsTxtUrl).toBe('https://acme.com/llms.txt');
  });

  it('parses variant B (all allow)', () => {
    const view = readSiteFacts(variantB);
    expect(view?.bots.every(({ stance }) => stance === 'allow')).toBe(true);
    expect(view?.bots.map(({ bot }) => bot)).toEqual([...AI_CRAWLER_BOTS]);
  });

  it('reports unknown stance for every bot when robots.txt was not fetched (fail-open is not a stance)', () => {
    // The backend records 'allow' for every bot on a missing/failed robots
    // fetch; the view must NOT present that as a real allow.
    const view = readSiteFacts({
      ...variantA,
      robots: {
        ...variantA.robots,
        fetched: false,
        status: 'fetch_failed',
        status_code: null,
      },
    });
    expect(view?.robotsFetched).toBe(false);
    expect(view?.robotsFetchStatus).toBe('fetch_failed');
    expect(view?.robotsStatus).toBeNull();
    expect(view?.bots.map(({ stance }) => stance)).toEqual([
      'unknown',
      'unknown',
      'unknown',
      'unknown',
    ]);
  });

  it('classifies a 404 robots.txt as not_found — every bot allowed by default (B2)', () => {
    // A 404 means the site HAS no robots.txt: the fail-open default IS the
    // real answer, so the stance is a definitive allow — not "unknown".
    const view = readSiteFacts({
      ...variantA,
      robots: {
        ...variantA.robots,
        fetched: false,
        status: 'not_found',
        status_code: 404,
      },
    });
    expect(view?.robotsFetchStatus).toBe('not_found');
    expect(view?.bots.every(({ stance }) => stance === 'allow')).toBe(true);
  });

  it('uses the explicit status token when the HTTP code differs', () => {
    // A fetch_failed token with a 404 status (a drifted blob) follows the
    // token — the worker's classification is authoritative.
    const view = readSiteFacts({
      ...variantA,
      robots: {
        ...variantA.robots,
        fetched: false,
        status: 'fetch_failed',
        status_code: 404,
      },
    });
    expect(view?.robotsFetchStatus).toBe('fetch_failed');
    expect(view?.bots.every(({ stance }) => stance === 'unknown')).toBe(true);
  });

  it.each([null, undefined, 'robots', 42, [], ['x']])(
    'returns null for absent/non-record input: %p',
    (input) => {
      expect(readSiteFacts(input)).toBeNull();
    },
  );

  it.each([
    {},
    { robots: variantA.robots }, // llms_txt missing
    { llms_txt: variantA.llms_txt }, // robots missing
    { robots: 'nope', llms_txt: variantA.llms_txt },
    { robots: variantA.robots, llms_txt: [1, 2] },
    { robots: null, llms_txt: null },
  ])('returns null when a sub-record is absent/malformed: %p', (input) => {
    expect(readSiteFacts(input)).toBeNull();
  });

  it('coerces partial records: missing status/URL → null, unknown stance token → unknown', () => {
    const view = readSiteFacts({
      robots: {
        fetched: true,
        status: 'fetched',
        url: '',
        status_code: '200',
        ai_crawlers: { GPTBot: 'disallow', ClaudeBot: 'allow' },
      },
      llms_txt: { fetched: true, present: 1 },
    });
    expect(view).not.toBeNull();
    expect(view?.robotsStatus).toBeNull();
    expect(view?.robotsUrl).toBeNull();
    expect(view?.bots).toEqual([
      { bot: 'GPTBot', stance: 'unknown' }, // unrecognized token
      { bot: 'ClaudeBot', stance: 'allow' },
      { bot: 'PerplexityBot', stance: 'unknown' }, // entry missing
      { bot: 'Google-Extended', stance: 'unknown' }, // entry missing
    ]);
    expect(view?.llmsTxtPresent).toBe(false); // non-boolean coerces to false
    expect(view?.llmsTxtStatus).toBeNull();
    expect(view?.llmsTxtUrl).toBeNull();
  });

  it('treats a missing/non-record ai_crawlers map as all-unknown (when fetched)', () => {
    const view = readSiteFacts({
      robots: {
        fetched: true,
        status: 'fetched',
        url: 'https://acme.com/robots.txt',
        status_code: 200,
      },
      llms_txt: { fetched: false, url: '', status_code: null, present: false },
    });
    expect(view?.bots.every(({ stance }) => stance === 'unknown')).toBe(true);
    expect(view?.llmsTxtFetched).toBe(false);
    expect(view?.llmsTxtPresent).toBe(false);
  });
});

describe('AI_CRAWLER_ENGINE_LABELS', () => {
  it('covers every known bot exactly once', () => {
    expect(Object.keys(AI_CRAWLER_ENGINE_LABELS).sort()).toEqual([...AI_CRAWLER_BOTS].sort());
    expect(AI_CRAWLER_ENGINE_LABELS.GPTBot).toBe('ChatGPT');
    expect(AI_CRAWLER_ENGINE_LABELS['Google-Extended']).toBe('Gemini / AI Overviews');
  });
});
