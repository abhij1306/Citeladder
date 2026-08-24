/**
 * Contract-drift guard tests (A5, ERR-5).
 *
 * Two layers:
 *   1. Pure `diffContract` unit tests over fixture specs — no backend needed.
 *   2. The live guard: acquire the backend OpenAPI document (deterministic
 *      offline codegen from the checked-in backend; see `acquireOpenApiSpec`)
 *      and FAIL on missing declared fields / unresolved mappings, WARN on
 *      additive-only diffs. When no schema source is available the guard
 *      logs and skips — run `pnpm check:contract` where a hard failure is
 *      required (CI).
 */
import { describe, expect, it } from 'vitest';

import {
  acquireOpenApiSpec,
  componentProperties,
  contractGuardIsStrict,
  CONTRACT_SCHEMA_MAP,
  declaredKeysFor,
  diffContract,
  type OpenApiSpec,
} from './contract-drift';

function specWith(components: Record<string, unknown>): OpenApiSpec {
  return { components: { schemas: components } } as OpenApiSpec;
}

describe('componentProperties', () => {
  it('reads flat properties and merges allOf/$ref branches', () => {
    const spec = specWith({
      Base: { properties: { id: {}, created_at: {} } },
      Child: {
        allOf: [
          { $ref: '#/components/schemas/Base' },
          { properties: { name: {} }, required: ['name'] },
        ],
      },
    });
    expect([...(componentProperties(spec, 'Child') ?? [])].sort()).toEqual([
      'created_at',
      'id',
      'name',
    ]);
    expect(componentProperties(spec, 'Missing')).toBeNull();
  });
});

describe('declaredKeysFor', () => {
  it('splits declared keys into required vs absent-tolerant', () => {
    const keys = declaredKeysFor('auditSchema');
    expect(keys).not.toBeNull();
    expect(keys?.declared).toContain('id');
    expect(keys?.declared).toContain('audit_scope');
    expect(keys?.required).toContain('id');
    expect(keys?.required).not.toContain('audit_scope');
  });

  it('resolves page wrappers and arrays to their object shape', () => {
    expect(declaredKeysFor('opportunitiesPageSchema')?.declared).toContain('items');
    expect(declaredKeysFor('visibilityTrendPointSchema')?.declared.length).toBeGreaterThan(0);
  });
});

describe('diffContract', () => {
  it('passes when declared fields match the component properties exactly', () => {
    const auditKeys = declaredKeysFor('auditSchema');
    const properties = Object.fromEntries((auditKeys?.declared ?? []).map((k) => [k, {}]));
    const result = diffContract(
      specWith({ ...realComponentsExcept(['AuditResponse']), AuditResponse: { properties } }),
    );
    expect(result.failures).toEqual([]);
    expect(result.warnings).toEqual([]);
    expect(result.drifts).toEqual([]);
  });

  it('FAILS on a missing declared field (drift the UI needs)', () => {
    const auditKeys = declaredKeysFor('auditSchema');
    const properties = Object.fromEntries(
      (auditKeys?.declared ?? []).filter((k) => k !== 'status').map((k) => [k, {}]),
    );
    const result = diffContract(
      specWith({ ...realComponentsExcept(['AuditResponse']), AuditResponse: { properties } }),
    );
    expect(result.failures).toHaveLength(1);
    expect(result.failures[0]).toContain('auditSchema');
    expect(result.failures[0]).toContain('status');
  });

  it('WARNS (never fails) on additive-only backend fields', () => {
    const auditKeys = declaredKeysFor('auditSchema');
    const properties = Object.fromEntries(
      [...(auditKeys?.declared ?? []), 'brand_new_field'].map((k) => [k, {}]),
    );
    const result = diffContract(
      specWith({ ...realComponentsExcept(['AuditResponse']), AuditResponse: { properties } }),
    );
    expect(result.failures).toEqual([]);
    expect(result.warnings).toHaveLength(1);
    expect(result.warnings[0]).toContain('brand_new_field');
  });

  it('orders additive machine keys independently of the runtime locale', () => {
    const auditKeys = declaredKeysFor('auditSchema');
    const properties = Object.fromEntries(
      [...(auditKeys?.declared ?? []), 'ä_field', 'z_field', 'A_field'].map((key) => [key, {}]),
    );
    const result = diffContract(
      specWith({ ...realComponentsExcept(['AuditResponse']), AuditResponse: { properties } }),
    );
    const drift = result.drifts.find((entry) => entry.schema === 'auditSchema');
    expect(drift?.additive).toEqual(['A_field', 'z_field', 'ä_field']);
  });

  it('does NOT fail when an absent-tolerant scope field is missing', () => {
    const auditKeys = declaredKeysFor('auditSchema');
    const properties = Object.fromEntries(
      (auditKeys?.declared ?? []).filter((k) => k !== 'audit_scope').map((k) => [k, {}]),
    );
    const result = diffContract(
      specWith({ ...realComponentsExcept(['AuditResponse']), AuditResponse: { properties } }),
    );
    expect(result.failures).toEqual([]);
  });

  it('fails on an unresolved mapping (the guard must stay maintainable)', () => {
    const result = diffContract(specWith({}));
    expect(result.unresolved.length).toBe(Object.keys(CONTRACT_SCHEMA_MAP).length);
    expect(result.failures.length).toBe(result.unresolved.length);
  });
});

/**
 * Every mapped component EXCEPT the named ones, drawn from the real zod
 * declared keys, so single-component fixture diffs above stay focused.
 */
function realComponentsExcept(exclude: string[]): Record<string, unknown> {
  const components: Record<string, unknown> = {};
  for (const [name, component] of Object.entries(CONTRACT_SCHEMA_MAP)) {
    if (exclude.includes(component)) continue;
    const keys = declaredKeysFor(name as keyof typeof CONTRACT_SCHEMA_MAP);
    components[component] = {
      properties: Object.fromEntries((keys?.declared ?? []).map((k) => [k, {}])),
    };
  }
  return components;
}

describe('backend contract drift guard', () => {
  it('has no missing declared fields against the backend OpenAPI models', async () => {
    const { acquired, errors } = await acquireOpenApiSpec();
    if (!acquired) {
      // Documented behavior (§6): the plain vitest wrapper skips when no
      // schema source is available, but `pnpm check:contract` / CI must FAIL
      // — otherwise the guard silently never runs where it matters most.
      const detail = `no OpenAPI source available:\n${errors.join('\n')}`;
      if (contractGuardIsStrict()) {
        throw new Error(
          `[contract-drift] ${detail}\n\nThe contract guard cannot run. Provide a spec via ` +
            'CITELADDER_OPENAPI_JSON, a working backend/.venv, or a reachable ' +
            'CITELADDER_BACKEND_ORIGIN.',
        );
      }
      console.warn(`[contract-drift] ${detail}\nSkipping the live guard.`);
      return;
    }
    const result = diffContract(acquired.spec);
    for (const warning of result.warnings) {
      console.warn(`[contract-drift] WARN (${acquired.source}): ${warning}`);
    }
    expect(result.failures, `contract drift via ${acquired.source}`).toEqual([]);
  }, 180_000);
});
