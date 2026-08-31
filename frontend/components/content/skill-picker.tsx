'use client';

import { RadioGroup } from '@/components/ui/radio-group';
import { Skeleton } from '@/components/ui/skeleton';
import type { ContentSkillView } from '@/lib/api/content';

/** Display order and copy for the channel groups the catalog reports. */
const CHANNEL_LABELS: Readonly<Record<string, string>> = {
  web: 'Web',
  social: 'Social',
  video: 'Video',
  community: 'Community',
  email: 'Email',
};

const CHANNEL_ORDER = ['web', 'social', 'video', 'community', 'email'] as const;

/** What the model will be told to do, shown before the user commits to it. */
function SkillDetail({ skill }: Readonly<{ skill: ContentSkillView }>) {
  return (
    <div className="max-w-xs p-1 text-xs">
      <p className="font-semibold">{skill.label}</p>
      <p className="mt-1 opacity-90">{skill.description}</p>
      {skill.structure.length > 0 ? (
        <ul className="border-on-inverse/20 text-2xs mt-1.5 grid list-disc gap-0.5 border-t pt-1.5 pl-4 opacity-80">
          {skill.structure.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ul>
      ) : null}
      {skill.length_hint ? <p className="text-2xs mt-1.5 opacity-75">{skill.length_hint}</p> : null}
    </div>
  );
}

/**
 * Skill picker for the content composer.
 *
 * The catalog is served by `GET /content/skills`, so this renders whatever the
 * backend offers rather than a hardcoded list — a skill added server-side
 * appears here with no frontend change. Each chip exposes the format's
 * structure on hover/focus so the choice is informed rather than a guess at
 * what "reddit" will produce.
 */
export function SkillPicker({
  skills,
  value,
  onChange,
  disabled = false,
  loading = false,
}: Readonly<{
  skills: readonly ContentSkillView[];
  value: string;
  onChange: (skillId: string) => void;
  disabled?: boolean;
  loading?: boolean;
}>) {
  if (loading) {
    return (
      <div className="flex flex-wrap gap-2" aria-busy="true">
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-7 w-24 rounded-full" />
        ))}
      </div>
    );
  }

  const byChannel = CHANNEL_ORDER.map((channel) => ({
    channel,
    label: CHANNEL_LABELS[channel] ?? channel,
    items: skills.filter((skill) => skill.channel === channel),
  })).filter((group) => group.items.length > 0);

  return (
    <RadioGroup
      value={value}
      onValueChange={onChange}
      ariaLabel="Content format"
      variant="chip"
      className="flex-col items-stretch gap-2"
      options={byChannel.flatMap((group) =>
        group.items.map((skill) => ({
          value: skill.id,
          label: skill.label,
          disabled,
          groupLabel: group.label,
          description: <SkillDetail skill={skill} />,
        })),
      )}
    />
  );
}
