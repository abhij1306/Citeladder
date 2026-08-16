'use client';

import { Check } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip } from '@/components/ui/tooltip';
import type { ContentSkillView } from '@/lib/api/content';
import { cn } from '@/lib/utils';

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
    <div
      role="radiogroup"
      aria-label="Content format"
      className="flex flex-col gap-2"
      data-component-id="content-skill-picker"
    >
      {byChannel.map((group) => (
        <div key={group.channel} className="flex flex-wrap items-center gap-1.5">
          <span className="text-muted text-2xs w-16 shrink-0 font-medium tracking-wider uppercase">
            {group.label}
          </span>
          {group.items.map((skill) => {
            const selected = skill.id === value;
            return (
              <Tooltip key={skill.id} content={<SkillDetail skill={skill} />}>
                <button
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={disabled}
                  onClick={() => onChange(skill.id)}
                  className={cn(
                    'focus-ring inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                    selected
                      ? 'border-accent-border bg-accent-soft text-accent-text font-medium'
                      : 'border-border text-secondary hover:border-border-strong hover:text-foreground',
                  )}
                >
                  {selected ? <Check className="size-3" aria-hidden /> : null}
                  {skill.label}
                </button>
              </Tooltip>
            );
          })}
        </div>
      ))}
    </div>
  );
}
