'use client';

import { useState } from 'react';

import { ChipRow, ChoiceChip, ReviewSection } from '@/components/onboarding/choice-controls';
import { Input } from '@/components/ui/input';
import type { DiscoveryProfile } from '@/lib/api/brand-discoveries';

/**
 * Everything the user actually decides at onboarding.
 *
 * Three questions, all answered by clicking. Positioning, description, target
 * audience and the product list used to live here as textareas; they are brand
 * knowledge, they belong on the brand screen inside the app, and nobody writes
 * prose about their own company at signup. The model fills them, they stay in
 * the payload, and they are editable later where that work belongs.
 *
 * "What you sell" is not one of three equal questions. Competitors, prompts and
 * every later score are derived from it, so a wrong category poisons the whole
 * project — and it is exactly the field the research model gets wrong on
 * businesses it half-recognises, most often by reading a firm that BUILDS
 * something as a firm that SELLS it. It therefore leads, carries the heavier
 * label, and states what it controls.
 */

export function hasConfirmedIcp(profile: DiscoveryProfile | null): profile is DiscoveryProfile {
  // Only the fields on this screen can gate it. Requiring invisible prose would
  // block the user on something they were never shown.
  return Boolean(profile?.category.trim());
}

const MARKET_SCOPE_CHOICES = [
  { value: 'local', label: 'City by city' },
  { value: 'national', label: 'Nationwide' },
  { value: 'regional', label: 'Across a region' },
  { value: 'global', label: 'Worldwide' },
] as const;

const BUYER_TYPE_CHOICES = [
  { value: 'b2c', label: 'Consumers' },
  { value: 'b2b', label: 'Businesses' },
  { value: 'both', label: 'Both' },
] as const;

const MAX_CATEGORY_CHOICES = 3;

/** Suggestions come only from model-supplied fields, never the live value. */
function categoryChoices(profile: DiscoveryProfile): string[] {
  const seen = new Set<string>();
  return [profile.category, ...profile.category_options, ...profile.category_aliases]
    .map((item) => item.trim())
    .filter((item) => {
      const key = item.toLowerCase();
      if (!item || seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, MAX_CATEGORY_CHOICES);
}

export function IcpConfirmation({
  profile,
  onChange,
}: Readonly<{
  profile: DiscoveryProfile;
  onChange: (profile: DiscoveryProfile) => void;
}>) {
  const update = <K extends keyof DiscoveryProfile>(key: K, value: DiscoveryProfile[K]) =>
    onChange({ ...profile, [key]: value });

  // Captured once so the list cannot shift under the user as they edit.
  const [choices] = useState(() => categoryChoices(profile));
  const [isOther, setIsOther] = useState(() => !choices.includes(profile.category));

  return (
    <div className="divide-border-subtle divide-y">
      <ReviewSection title="What you sell" emphasis>
        <p className="text-muted -mt-1 mb-1 text-sm font-medium">
          Your competitors and tracked questions are built from this.
        </p>
        <ChipRow>
          {choices.map((option) => (
            <ChoiceChip
              key={option}
              name="category"
              label={option}
              selected={!isOther && profile.category === option}
              onSelect={() => {
                setIsOther(false);
                update('category', option);
              }}
            />
          ))}
          {/* Separated from the suggestions: an escape hatch is not a fourth
              peer option, and reading it as one made a wrong guess look like a
              menu the right answer was simply missing from. */}
          <span aria-hidden className="bg-border-strong mx-1.5 h-4 w-px self-center" />
          <ChoiceChip
            name="category"
            label={choices.length > 0 ? 'None of these' : 'Other'}
            selected={isOther}
            onSelect={() => {
              setIsOther(true);
              // Rejecting the suggestions has to DROP the rejected one, or the
              // empty-looking text field submits the very suggestion the user
              // just said was wrong. Cleared on the same condition the field
              // blanks itself on, so re-clicking never wipes typed text.
              if (choices.includes(profile.category)) update('category', '');
            }}
          />
        </ChipRow>

        {isOther ? (
          <div className="pt-1">
            <Input
              autoFocus
              aria-label="Describe what you sell"
              value={choices.includes(profile.category) ? '' : profile.category}
              onChange={(event) => update('category', event.target.value)}
              placeholder="e.g. ecommerce implementation agency"
              className="max-w-md shadow-2xs"
            />
          </div>
        ) : null}
      </ReviewSection>

      <ReviewSection title="Who buys it">
        <ChipRow>
          {BUYER_TYPE_CHOICES.map((choice) => (
            <ChoiceChip
              key={choice.value}
              name="buyer_type"
              label={choice.label}
              selected={profile.business_type === choice.value}
              onSelect={() => update('business_type', choice.value)}
            />
          ))}
        </ChipRow>
      </ReviewSection>

      <ReviewSection title="Where they buy it">
        <ChipRow>
          {MARKET_SCOPE_CHOICES.map((choice) => (
            <ChoiceChip
              key={choice.value}
              name="market_scope"
              label={choice.label}
              selected={profile.market_scope === choice.value}
              onSelect={() => update('market_scope', choice.value)}
            />
          ))}
        </ChipRow>
      </ReviewSection>
    </div>
  );
}
