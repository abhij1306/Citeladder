import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  cloneFingerprint,
  productionFailures,
  readReport,
  validateBaseline,
} from './check-jscpd.mjs';

function cloneFixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'jscpd-clone-test-'));
  const first = path.join(directory, 'first.ts');
  const second = path.join(directory, 'second.ts');
  fs.writeFileSync(first, 'const shared = true;\n');
  fs.writeFileSync(second, 'const shared = true;\n');
  return {
    directory,
    clone: {
      format: 'typescript',
      lines: 1,
      tokens: 4,
      firstFile: { name: second, start: 1, end: 1 },
      secondFile: { name: first, start: 1, end: 1 },
    },
  };
}

describe('jscpd ratchet', () => {
  it('normalizes clone identity across path separators and report ordering', () => {
    const { directory, clone } = cloneFixture();
    try {
      const fingerprint = cloneFingerprint(clone);
      expect(fingerprint).toMatch(/typescript\|.*first\.ts\|.*second\.ts\|[0-9a-f]{16}\|1\|4/);
      expect(
        cloneFingerprint({ ...clone, firstFile: clone.secondFile, secondFile: clone.firstFile }),
      ).toBe(fingerprint);
    } finally {
      fs.rmSync(directory, { recursive: true, force: true });
    }
  });

  it('keeps clone identity stable across ignored whitespace and comments', () => {
    const { directory, clone } = cloneFixture();
    try {
      const fingerprint = cloneFingerprint(clone);
      fs.writeFileSync(clone.firstFile.name, '// moved\n  const shared = true;\n');
      fs.writeFileSync(clone.secondFile.name, '/* moved */\nconst   shared=true;\n');
      const moved = {
        ...clone,
        firstFile: { ...clone.firstFile, start: 2, end: 2 },
        secondFile: { ...clone.secondFile, start: 2, end: 2 },
      };
      expect(cloneFingerprint(moved)).toBe(fingerprint);
    } finally {
      fs.rmSync(directory, { recursive: true, force: true });
    }
  });

  it('rejects a new clone even when aggregate duplication stays below the threshold', () => {
    const { directory, clone } = cloneFixture();
    const baseline = validateBaseline({
      format_version: 1,
      tool_version: '5.0.11',
      scope: ['backend/app', 'frontend/app', 'frontend/components', 'frontend/lib'],
      production_percentage: 1,
      clone_fingerprints: [],
    });
    const report = {
      duplicates: [clone],
      statistics: { total: { percentage: 0.1 } },
    };

    try {
      expect(productionFailures(report, baseline)).toEqual([
        `new production clone: ${cloneFingerprint(clone)}`,
      ]);
    } finally {
      fs.rmSync(directory, { recursive: true, force: true });
    }
  });

  it('counts repeated identical clone fingerprints instead of collapsing them', () => {
    const { directory, clone } = cloneFixture();
    const fingerprint = cloneFingerprint(clone);
    const baseline = validateBaseline({
      format_version: 1,
      tool_version: '5.0.11',
      scope: ['backend/app', 'frontend/app', 'frontend/components', 'frontend/lib'],
      production_percentage: 1,
      clone_fingerprints: [fingerprint],
    });
    try {
      expect(
        productionFailures(
          { duplicates: [clone, clone], statistics: { total: { percentage: 0.1 } } },
          baseline,
        ),
      ).toEqual([`new production clone: ${fingerprint}`]);
    } finally {
      fs.rmSync(directory, { recursive: true, force: true });
    }
  });

  it('rejects relaxing a percentage or accepting a new baseline fingerprint', () => {
    const base = validateBaseline({
      format_version: 1,
      tool_version: '5.0.11',
      scope: ['backend/app', 'frontend/app', 'frontend/components', 'frontend/lib'],
      production_percentage: 0.1,
      clone_fingerprints: [],
    });
    const current = validateBaseline({
      format_version: 1,
      tool_version: '5.0.11',
      scope: ['backend/app', 'frontend/app', 'frontend/components', 'frontend/lib'],
      production_percentage: 0.2,
      clone_fingerprints: ['typescript|a.ts|b.ts|20|200'],
    });

    expect(
      productionFailures({ duplicates: [], statistics: { total: {} } }, current, base),
    ).toEqual([
      'stale accepted clone fingerprint: typescript|a.ts|b.ts|20|200',
      'jscpd percentage threshold was relaxed',
      'new accepted clone fingerprint is forbidden: typescript|a.ts|b.ts|20|200',
    ]);
  });

  it('treats a missing zero-clone JSON report as an empty result', () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'jscpd-test-'));
    try {
      expect(readReport(path.join(directory, 'missing.json'))).toEqual({
        duplicates: [],
        statistics: { total: { percentage: 0 } },
      });
    } finally {
      fs.rmSync(directory, { recursive: true, force: true });
    }
  });
});
