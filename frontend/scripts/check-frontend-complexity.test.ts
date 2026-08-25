import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import {
  failuresFor,
  measure,
  policyDiffFailures,
  staleExceptionFailures,
  validatePolicy,
} from './check-frontend-complexity.mjs';

const tempDirs: string[] = [];
type Policy = {
  format_version: number;
  roots: string[];
  defaults: {
    max_function_cc: number;
    max_production_loc: number;
    max_test_loc: number;
  };
  exceptions: {
    functions: Record<string, number>;
    modules: Record<string, number>;
  };
};

const basePolicy = (): Policy => ({
  format_version: 1,
  roots: ['app', 'components', 'lib'],
  defaults: { max_function_cc: 15, max_production_loc: 900, max_test_loc: 900 },
  exceptions: { functions: {}, modules: {} },
});

afterEach(() => {
  for (const directory of tempDirs.splice(0))
    fs.rmSync(directory, { recursive: true, force: true });
});

function fixture(source: string, name = 'fixture.ts') {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'citeladder-complexity-test-'));
  tempDirs.push(directory);
  const file = path.join(directory, name);
  fs.writeFileSync(file, source);
  return file;
}

describe('frontend complexity checker', () => {
  it('measures cyclomatic complexity and lines of code', () => {
    const result = measure(
      fixture(
        'export function run(value: boolean) {\n  if (value && !value) return 1;\n  return 0;\n}\n',
      ),
    );
    expect(result.loc).toBe(5);
    expect(result.functions).toEqual([{ name: 'run', cc: 3, line: 1 }]);
  });

  it('rejects function and module regressions while accepting ceilings', () => {
    const policy = basePolicy();
    const measurements = {
      'fixture.ts': { loc: 901, test: false, functions: [{ name: 'run', cc: 16, line: 1 }] },
    };
    expect(failuresFor(measurements, policy)).toHaveLength(2);
    policy.exceptions.modules['fixture.ts'] = 901;
    policy.exceptions.functions['fixture.ts::run'] = 16;
    expect(failuresFor(measurements, policy)).toEqual([]);
  });

  it('reports stale module and function exceptions', () => {
    const policy = basePolicy();
    policy.exceptions.modules['gone.ts'] = 901;
    policy.exceptions.functions['fixture.ts::gone'] = 16;
    const measurements = {
      'fixture.ts': { loc: 20, test: false, functions: [{ name: 'run', cc: 3, line: 1 }] },
    };
    expect(staleExceptionFailures(measurements, policy)).toEqual([
      'stale module exception: gone.ts does not exist',
      'stale function exception: fixture.ts::gone does not exist',
    ]);
  });

  it('rejects new and increased exceptions plus root/default policy changes', () => {
    const base = basePolicy();
    const current = basePolicy();
    base.exceptions.functions['fixture.ts::run'] = 16;
    current.exceptions.functions['fixture.ts::run'] = 17;
    current.exceptions.modules['new.ts'] = 902;
    expect(policyDiffFailures(base, current)).toEqual(
      expect.arrayContaining([
        'new module exception is forbidden: new.ts',
        'function exception fixture.ts::run increased 16 -> 17',
      ]),
    );
    expect(() => validatePolicy({ ...basePolicy(), roots: ['app', 'lib'] })).toThrow(/roots/);
    const relaxedDefaults = basePolicy();
    relaxedDefaults.defaults.max_function_cc = 16;
    expect(() => validatePolicy(relaxedDefaults)).toThrow(/defaults/);
  });

  it('gives anonymous callbacks position-qualified identities', () => {
    const file = fixture(
      'const callbacks = [() => 1, () => 2];\nconst objects = [{ handler: () => 3 }, { handler: () => 4 }];\n',
    );
    const names = measure(file).functions.map((fn: { name: string }) => fn.name);
    expect(new Set(names).size).toBe(names.length);
    expect(names.filter((name: string) => name.startsWith('<anonymous>@'))).toHaveLength(2);
    expect(names).toEqual([
      '<anonymous>@1:20',
      '<anonymous>@1:29',
      'handler::<anonymous>@2:29',
      'handler::<anonymous>@2:51',
    ]);
  });
});
