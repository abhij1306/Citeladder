import { describe, expect, it } from 'vitest';

import {
  brandStepSchema,
  deriveDomain,
  normalizeWebsiteUrl,
  onboardingErrorMessage,
  type BrandStepValues,
} from './forms';

const brand: BrandStepValues = {
  brand_name: '  Acme  ',
  website_url: 'acme.com',
  primary_market: 'US',
  language_code: 'en',
  industry: 'Analytics',
  subindustry: '',
};

describe('normalizeWebsiteUrl', () => {
  it('adds a scheme to a bare host', () => {
    expect(normalizeWebsiteUrl('acme.com')).toBe('https://acme.com');
  });

  it('leaves an explicit scheme alone, including http', () => {
    expect(normalizeWebsiteUrl('https://acme.com')).toBe('https://acme.com');
    expect(normalizeWebsiteUrl('http://acme.com')).toBe('http://acme.com');
  });

  it('is empty for empty input rather than producing "https://"', () => {
    expect(normalizeWebsiteUrl('   ')).toBe('');
  });
});

describe('deriveDomain', () => {
  it('strips scheme, www and path', () => {
    expect(deriveDomain('https://www.acme.com/pricing')).toBe('acme.com');
    expect(deriveDomain('acme.co.uk')).toBe('acme.co.uk');
  });

  it('returns empty for input that cannot parse', () => {
    expect(deriveDomain('')).toBe('');
    expect(deriveDomain('   ')).toBe('');
    expect(deriveDomain('ftp://acme.com')).toBe('');
  });
});

describe('brandStepSchema', () => {
  it('accepts a bare host and a full URL', () => {
    expect(brandStepSchema.safeParse({ ...brand, website_url: 'acme.com' }).success).toBe(true);
    expect(brandStepSchema.safeParse({ ...brand, website_url: 'https://acme.com' }).success).toBe(
      true,
    );
  });

  it('rejects a website with no dot', () => {
    expect(brandStepSchema.safeParse({ ...brand, website_url: 'acme' }).success).toBe(false);
  });

  it('rejects non-HTTP website schemes', () => {
    expect(brandStepSchema.safeParse({ ...brand, website_url: 'ftp://acme.com' }).success).toBe(
      false,
    );
    expect(brandStepSchema.safeParse({ ...brand, website_url: 'file://acme.com' }).success).toBe(
      false,
    );
  });

  it('requires a brand name', () => {
    expect(brandStepSchema.safeParse({ ...brand, brand_name: '   ' }).success).toBe(false);
  });
});

describe('onboardingErrorMessage', () => {
  it('prefers the transport-unwrapped detail', () => {
    expect(onboardingErrorMessage(new Error('Brand already exists.'))).toBe(
      'Brand already exists.',
    );
  });

  it('falls back for non-errors', () => {
    expect(onboardingErrorMessage(null)).toMatch(/something went wrong/i);
  });
});
