import { describe, expect, it } from 'vitest';

import { commerceCatalogSchema, shelfSchema } from './schemas/commerce-suite';

describe('Commerce replacement contracts', () => {
  it('keeps catalog provenance and empty persisted shelf states explicit', () => {
    const catalog = commerceCatalogSchema.parse({
      products: [],
      categories: [],
      projection_tasks: { queued: 1 },
    });
    expect(catalog.projection_tasks.queued).toBe(1);
    expect(shelfSchema.parse({ snapshots: [], observations: [] })).toEqual({
      snapshots: [],
      observations: [],
    });
  });
});
