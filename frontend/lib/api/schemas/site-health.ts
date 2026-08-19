/**
 * Stable Site Health schema facade.
 *
 * Keep all Site Health consumers importing this module (or `schemas.ts`). The
 * focused modules below keep the API contracts reviewable without changing the
 * inferred Zod schema identities or their public names.
 */
export * from './site-health/crawl';
export * from './site-health/dashboard';
export * from './site-health/inventory';
export * from './site-health/issues';
export * from './site-health/pages';
export * from './site-health/pagination';
