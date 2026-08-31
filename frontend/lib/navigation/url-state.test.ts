import { describe, expect, it } from 'vitest';

import { optionalStringUrlCodec, stringUrlCodec } from './url-state';

describe('URL state codecs', () => {
  it('canonicalizes invalid enums to the default and omits that default', () => {
    const codec = stringUrlCodec(['overview', 'issues'] as const, 'overview');
    expect(codec.parse('issues')).toBe('issues');
    expect(codec.parse('unknown')).toBe('overview');
    expect(codec.serialize('overview')).toBeNull();
    expect(codec.serialize('issues')).toBe('issues');
  });

  it('round-trips optional selected IDs', () => {
    expect(optionalStringUrlCodec.parse('issue-id')).toBe('issue-id');
    expect(optionalStringUrlCodec.serialize(null)).toBeNull();
  });
});
