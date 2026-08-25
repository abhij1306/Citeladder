// @vitest-environment node
//
// Pure logic: no DOM, no window, no React render. The suite-wide jsdom
// default costs a full environment per file and buys nothing here.
import { describe, expect, it } from 'vitest';

import { formErrorMessage } from './error-message';

const FALLBACK = 'Something went wrong. Please try again.';

/**
 * `lib/forms` had no tests. This helper decides what a user reads after a
 * failed submit, so the branch that matters is the one where the thrown value
 * carries nothing usable: a blank or non-Error rejection must still produce a
 * sentence rather than an empty string or "[object Object]".
 */
describe('formErrorMessage', () => {
  it('uses a real Error message', () => {
    expect(formErrorMessage(new Error('Website is required'))).toBe('Website is required');
  });

  it.each([
    ['an empty message', new Error('')],
    ['a whitespace-only message', new Error('   ')],
  ])('falls back for %s', (_name, error) => {
    expect(formErrorMessage(error)).toBe(FALLBACK);
  });

  it('keeps meaningful whitespace-padded text as-is', () => {
    // Trimming is only used to DECIDE whether the message is empty; the
    // message itself is passed through unchanged.
    expect(formErrorMessage(new Error(' Website is required '))).toBe(' Website is required ');
  });

  it.each([
    ['a string rejection', 'boom'],
    ['a plain object', { message: 'boom' }],
    ['null', null],
    ['undefined', undefined],
  ])('falls back for %s', (_name, thrown) => {
    expect(formErrorMessage(thrown)).toBe(FALLBACK);
  });

  it('uses the message of an Error subclass', () => {
    class ApiFailure extends Error {}
    expect(formErrorMessage(new ApiFailure('Rate limited'))).toBe('Rate limited');
  });
});
