import { describe, expect, it } from 'vitest';

import { ACTIVE_RUN_POLL_MS } from '@/lib/config/operational';
import { catalogPollingInterval } from './catalog-polling';

describe('catalogPollingInterval', () => {
  it('polls only while projection work is in flight', () => {
    expect(catalogPollingInterval({ running: 1 })).toBe(ACTIVE_RUN_POLL_MS);
    expect(catalogPollingInterval({ queued: 2, succeeded: 30 })).toBe(ACTIVE_RUN_POLL_MS);
    expect(catalogPollingInterval({ retry_wait: 1 })).toBe(ACTIVE_RUN_POLL_MS);
  });

  it('stops once every task has terminalized', () => {
    // The old rule polled every three seconds forever, to re-learn that a
    // finished crawl was still finished.
    expect(catalogPollingInterval({ succeeded: 36, failed: 2 })).toBe(false);
    expect(catalogPollingInterval({})).toBe(false);
    expect(catalogPollingInterval(undefined)).toBe(false);
  });

  it('treats a zero count as no work', () => {
    expect(catalogPollingInterval({ running: 0, queued: 0, succeeded: 5 })).toBe(false);
  });
});
