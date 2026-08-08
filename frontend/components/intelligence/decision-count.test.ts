import { describe, expect, it } from 'vitest';

import type { DecisionKind } from './decision-prompt';

/**
 * The two-decisions rule (§1), pinned as a type-level and value-level test.
 *
 * The user is asked exactly twice: save content, and run or schedule an audit.
 * No approval queue, no review inbox, no promotion step. If a screen appears
 * to need a third decision point the design is wrong — the plan says to go
 * back to the layer plan rather than add a gate, and this test is what makes
 * that conversation happen instead of the gate quietly appearing.
 *
 * `EXHAUSTIVE_DECISIONS` is typed as `Record<DecisionKind, true>`, so adding a
 * member to `DecisionKind` fails the type check here until someone
 * deliberately edits this file.
 */
const EXHAUSTIVE_DECISIONS: Record<DecisionKind, true> = {
  'save-content': true,
  'run-audit': true,
};

describe('Decision count', () => {
  it('blocks on exactly two decisions', () => {
    expect(Object.keys(EXHAUSTIVE_DECISIONS)).toHaveLength(2);
  });

  it('blocks on saving content and running an audit, and nothing else', () => {
    expect(Object.keys(EXHAUSTIVE_DECISIONS).sort()).toEqual(['run-audit', 'save-content']);
  });
});
