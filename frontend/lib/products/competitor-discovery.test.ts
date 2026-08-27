import { describe, expect, it } from 'vitest';

import { ACTIVE_RUN_POLL_MS } from '@/lib/config/operational';
import { discoveryPollInterval, discoverySettled } from './competitor-discovery';

const task = (id: string, status: string, terminal: boolean) => ({
  id,
  target: { kind: 'category' as const, id: '22222222-2222-4222-8222-222222222222' },
  status,
  error_code: '',
  terminal,
});

describe('discoveryPollInterval', () => {
  it('polls while any tracked discovery is still running', () => {
    expect(discoveryPollInterval([task('a', 'running', false)])).toBe(ACTIVE_RUN_POLL_MS);
    expect(discoveryPollInterval([task('a', 'succeeded', true), task('b', 'queued', false)])).toBe(
      ACTIVE_RUN_POLL_MS,
    );
  });

  it('stops once every tracked discovery has terminalized', () => {
    expect(discoveryPollInterval([task('a', 'succeeded', true), task('b', 'failed', true)])).toBe(
      false,
    );
    expect(discoveryPollInterval([])).toBe(false);
    expect(discoveryPollInterval(undefined)).toBe(false);
  });
});

describe('discoverySettled', () => {
  it('fires on the read where the tracked tasks are all terminal', () => {
    expect(discoverySettled([task('a', 'running', false)], [task('a', 'succeeded', true)])).toBe(
      true,
    );
    expect(discoverySettled(undefined, [task('a', 'failed', true)])).toBe(true);
    expect(discoverySettled(undefined, [task('a', 'cancelled', true)])).toBe(true);
  });

  it('fires when the recovered in-flight list empties after a reload', () => {
    expect(discoverySettled([task('a', 'running', false)], [])).toBe(true);
  });

  it('does not fire while work is still running, or when nothing ever ran', () => {
    expect(discoverySettled([task('a', 'running', false)], [task('a', 'running', false)])).toBe(
      false,
    );
    expect(discoverySettled([task('a', 'succeeded', true)], [task('b', 'queued', false)])).toBe(
      false,
    );
    expect(discoverySettled(undefined, [])).toBe(false);
    expect(discoverySettled([], [])).toBe(false);
  });
});
