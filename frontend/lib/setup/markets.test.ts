// @vitest-environment node
//
// Pure logic: no DOM, no window, no React render. The suite-wide jsdom
// default costs a full environment per file and buys nothing here.
import { describe, expect, it } from 'vitest';

import { COUNTRY_OPTIONS, LANGUAGE_OPTIONS } from './markets';

/**
 * `lib/setup` had no tests. These options feed the guided setup's selects and
 * are submitted verbatim as `country_code` / `language_code`, so a malformed
 * entry is not a cosmetic problem — it is a create request the backend rejects
 * for a value the user could not have typed wrong.
 *
 * The shapes asserted here are the ones the module documents: a 2-letter
 * uppercase country, and a language that is either 2 lowercase letters or
 * `xx-YY`.
 */
const COUNTRY_CODE = /^[A-Z]{2}$/;
const LANGUAGE_CODE = /^[a-z]{2}(-[A-Z]{2})?$/;

describe('market options', () => {
  it.each([
    ['country', COUNTRY_OPTIONS],
    ['language', LANGUAGE_OPTIONS],
  ])('offers %s choices with non-empty labels', (_name, options) => {
    expect(options.length).toBeGreaterThan(0);
    for (const option of options) {
      expect(option.label.trim(), option.value).not.toBe('');
    }
  });

  it('uses well-formed country codes', () => {
    for (const option of COUNTRY_OPTIONS) {
      expect(option.value, option.label).toMatch(COUNTRY_CODE);
    }
  });

  it('uses well-formed language codes', () => {
    for (const option of LANGUAGE_OPTIONS) {
      expect(option.value, option.label).toMatch(LANGUAGE_CODE);
    }
  });

  it.each([
    ['country', COUNTRY_OPTIONS],
    ['language', LANGUAGE_OPTIONS],
  ])('has no duplicate %s values', (_name, options) => {
    const values = options.map((option) => option.value);
    // A duplicate value makes two select entries indistinguishable to React's
    // keying and to the user.
    expect(new Set(values).size).toBe(values.length);
  });

  it.each([
    ['country', COUNTRY_OPTIONS],
    ['language', LANGUAGE_OPTIONS],
  ])('has no duplicate %s labels', (_name, options) => {
    const labels = options.map((option) => option.label);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it('offers a plain base language alongside every regional variant', () => {
    // `en-GB` without `en` would leave a user unable to pick the generic
    // language the backend treats as the default.
    const values = new Set(LANGUAGE_OPTIONS.map((option) => option.value));
    for (const value of values) {
      if (!value.includes('-')) continue;
      expect(values.has(value.split('-')[0]!), value).toBe(true);
    }
  });
});
