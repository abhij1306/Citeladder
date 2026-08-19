import { describe, expect, it } from 'vitest';

import type { Prompt, Topic } from '@/lib/api/types';

import { groupByTopic } from './topic-groups';

const topic = { id: 'topic-1', name: 'Growth' } as Topic;
const prompt = (id: string, topicId: string | null) => ({ id, topic_id: topicId }) as Prompt;

describe('groupByTopic', () => {
  it('keeps missing-topic and unassigned prompts together as Ungrouped', () => {
    const groups = groupByTopic(
      [prompt('assigned', topic.id), prompt('missing', 'deleted-topic'), prompt('plain', null)],
      [topic],
      new Map([
        ['assigned', 80],
        ['missing', 60],
      ]),
    );

    expect(groups).toEqual([
      expect.objectContaining({
        key: topic.id,
        prompts: [prompt('assigned', topic.id)],
        score: 80,
      }),
      expect.objectContaining({
        key: 'ungrouped',
        prompts: [prompt('plain', null), prompt('missing', 'deleted-topic')],
        score: 60,
      }),
    ]);
  });
});
