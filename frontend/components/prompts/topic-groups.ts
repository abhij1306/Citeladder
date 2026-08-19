import type { Prompt, Topic } from '@/lib/api/types';

export type TopicGroup = {
  key: string;
  topic: Topic | null;
  prompts: Prompt[];
  /** Mean of the group's measured prompt scores; null until any prompt has data. */
  score: number | null;
};

type PromptBuckets = Map<string | null, Prompt[]>;

function bucketPrompts(prompts: Prompt[]): PromptBuckets {
  const buckets: PromptBuckets = new Map();
  for (const prompt of prompts) {
    const key = prompt.topic_id ?? null;
    const bucket = buckets.get(key) ?? [];
    bucket.push(prompt);
    buckets.set(key, bucket);
  }
  return buckets;
}

function knownTopicGroups(topics: Topic[], buckets: PromptBuckets): TopicGroup[] {
  return topics.flatMap((topic) => {
    const prompts = buckets.get(topic.id) ?? [];
    return prompts.length ? [{ key: topic.id, topic, prompts, score: null }] : [];
  });
}

function ungroupedPrompts(topics: Topic[], buckets: PromptBuckets): Prompt[] {
  const knownTopicIds = new Set(topics.map((topic) => topic.id));
  const ungrouped = [...(buckets.get(null) ?? [])];
  for (const [topicId, prompts] of buckets) {
    if (topicId !== null && !knownTopicIds.has(topicId)) ungrouped.push(...prompts);
  }
  return ungrouped;
}

function averageScore(prompts: Prompt[], scores: Map<string, number>): number | null {
  const measured = prompts.flatMap((prompt) => {
    const score = scores.get(prompt.id);
    return score === undefined ? [] : [score];
  });
  if (!measured.length) return null;
  return Math.round(measured.reduce((sum, score) => sum + score, 0) / measured.length);
}

/** Groups prompts by their live topic, preserving orphaned rows under Ungrouped. */
export function groupByTopic(
  prompts: Prompt[],
  topics: Topic[],
  scores: Map<string, number>,
): TopicGroup[] {
  const buckets = bucketPrompts(prompts);
  const groups = knownTopicGroups(topics, buckets);
  const ungrouped = ungroupedPrompts(topics, buckets);
  if (ungrouped.length)
    groups.push({ key: 'ungrouped', topic: null, prompts: ungrouped, score: null });
  return groups.map((group) => ({ ...group, score: averageScore(group.prompts, scores) }));
}
