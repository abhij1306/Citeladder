import { afterEach, describe, expect, it } from 'vitest';

import { absoluteUrl, SITE_NAME, SITE_TAGLINE, siteOrigin } from './site';

const ORIGINAL = process.env.NEXT_PUBLIC_SITE_URL;

afterEach(() => {
  if (ORIGINAL === undefined) {
    delete process.env.NEXT_PUBLIC_SITE_URL;
  } else {
    process.env.NEXT_PUBLIC_SITE_URL = ORIGINAL;
  }
});

describe('siteOrigin', () => {
  it('returns null when NEXT_PUBLIC_SITE_URL is unset', () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;
    expect(siteOrigin()).toBeNull();
  });

  it('returns null for a non-https origin', () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'http://app.citeladder.com';
    expect(siteOrigin()).toBeNull();
  });

  it('returns null when credentials are present', () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'https://user:pass@app.citeladder.com';
    expect(siteOrigin()).toBeNull();
  });

  it('returns null for an unparseable value', () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'not a url';
    expect(siteOrigin()).toBeNull();
  });

  it('returns a URL for a valid https origin', () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'https://app.citeladder.com';
    const origin = siteOrigin();
    expect(origin).toBeInstanceOf(URL);
    expect(origin?.origin).toBe('https://app.citeladder.com');
  });
});

describe('absoluteUrl', () => {
  it('returns null while no origin is configured', () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;
    expect(absoluteUrl('/faq')).toBeNull();
  });

  it('resolves a path against the configured origin', () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'https://app.citeladder.com';
    expect(absoluteUrl('/faq')).toBe('https://app.citeladder.com/faq');
    expect(absoluteUrl('/')).toBe('https://app.citeladder.com/');
  });
});

describe('site constants', () => {
  it('pins the product name and tagline', () => {
    expect(SITE_NAME).toBe('CiteLadder');
    expect(SITE_TAGLINE).toBe('AI visibility analytics');
  });
});
