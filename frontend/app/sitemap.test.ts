import { afterEach, describe, expect, it } from 'vitest';

import { POSTS } from '@/lib/marketing-content/blog';
import { COMPETITORS } from '@/lib/marketing-content/compare';

import manifest from './manifest';
import robots from './robots';
import sitemap from './sitemap';

const ORIGINAL = process.env.NEXT_PUBLIC_SITE_URL;

afterEach(() => {
  if (ORIGINAL === undefined) {
    delete process.env.NEXT_PUBLIC_SITE_URL;
  } else {
    process.env.NEXT_PUBLIC_SITE_URL = ORIGINAL;
  }
});

const STATIC_PATHS = [
  '/',
  '/pricing',
  '/enterprise',
  '/solutions',
  '/demo',
  '/faq',
  '/blog',
  '/compare',
  '/register',
  '/login',
] as const;

describe('sitemap', () => {
  it('contains every public route plus one entry per post and per comparison', () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;
    const urls = sitemap().map((entry) => entry.url);
    expect(urls).toHaveLength(STATIC_PATHS.length + POSTS.length + COMPETITORS.length);
    for (const path of STATIC_PATHS) {
      expect(urls).toContain(path);
    }
    for (const post of POSTS) {
      expect(urls).toContain(`/blog/${post.slug}`);
    }
    for (const competitor of COMPETITORS) {
      expect(urls).toContain(`/compare/${competitor.slug}`);
    }
  });

  it('emits path-only entries without throwing while no origin is configured', () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;
    expect(() => sitemap()).not.toThrow();
    for (const entry of sitemap()) {
      expect(entry.url).toMatch(/^\//);
    }
  });

  it('absolutizes entries once a canonical origin exists', () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'https://app.citeladder.com';
    for (const entry of sitemap()) {
      expect(entry.url).toMatch(/^https:\/\/app\.citeladder\.com\//);
    }
  });
});

describe('robots', () => {
  it('keeps the signed-in app and API out of the crawl', () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;
    const result = robots();
    const rules = Array.isArray(result.rules) ? result.rules : [result.rules];
    expect(rules[0]?.userAgent).toBe('*');
    expect(rules[0]?.allow).toBe('/');
    const disallow = rules[0]?.disallow;
    expect(disallow).toEqual(
      expect.arrayContaining([
        '/api/',
        '/onboarding',
        '/visibility',
        '/ai-referrals',
        '/traffic',
        '/prompts',
        '/products',
        '/runs',
        '/content',
        '/site',
        '/issues',
        '/opportunities',
        '/projects',
        '/settings',
      ]),
    );
  });

  it('omits the sitemap directive while no origin is configured', () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;
    expect(robots()).not.toHaveProperty('sitemap');
  });

  it('emits an absolute sitemap URL once an origin exists', () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'https://app.citeladder.com';
    expect(robots().sitemap).toBe('https://app.citeladder.com/sitemap.xml');
  });
});

describe('manifest', () => {
  it('carries no literal hex colours (design-token guard)', () => {
    const result = manifest();
    expect(result.name).toBe('CiteLadder');
    expect(result.start_url).toBe('/');
    expect(result.icons).toEqual([
      { src: '/citeladder-favicon.ico', type: 'image/x-icon', sizes: '256x256' },
    ]);
    expect(result).not.toHaveProperty('theme_color');
    expect(result).not.toHaveProperty('background_color');
  });
});
