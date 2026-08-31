'use client';

import { useState } from 'react';

import { ReviewSection } from '@/components/onboarding/choice-controls';
import { Input } from '@/components/ui/input';
import { RadioGroup } from '@/components/ui/radio-group';
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
  { value: 'national', label: 'Nationwide' },
  { value: 'regional', label: 'Regional' },
  { value: 'global', label: 'Worldwide' },
] as const;

const BUYER_TYPE_CHOICES = [
  { value: 'b2c', label: 'Consumers' },
  { value: 'b2b', label: 'Businesses' },
  { value: 'both', label: 'Both' },
] as const;

const MAX_CATEGORY_CHOICES = 3;
const OTHER_CATEGORY = '__other__';

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
    <div>
      <ReviewSection title="What you sell" className="pt-0">
        <p className="text-muted -mt-1 mb-1 text-sm font-medium">
          Your competitors and tracked questions are built from this.
        </p>
        <RadioGroup
          variant="chip"
          ariaLabel="What you sell"
          value={isOther ? OTHER_CATEGORY : profile.category}
          options={[
            ...choices.map((option) => ({ value: option, label: option })),
            { value: OTHER_CATEGORY, label: choices.length > 0 ? 'None of these' : 'Other' },
          ]}
          onValueChange={(value) => {
            if (value === OTHER_CATEGORY) {
              setIsOther(true);
              if (choices.includes(profile.category)) update('category', '');
            } else {
              setIsOther(false);
              update('category', value);
            }
          }}
        />

        {isOther ? (
          <div className="pt-1">
            <Input
              // oxlint-disable-next-line jsx-a11y/no-autofocus -- Choosing Other explicitly reveals this field; focus follows that user action.
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

      <div className="border-border-subtle grid border-t md:grid-cols-2">
        <ReviewSection title="Who buys it" className="md:pr-4">
          <RadioGroup
            variant="chip"
            ariaLabel="Who buys it"
            value={profile.business_type}
            options={BUYER_TYPE_CHOICES}
            onValueChange={(value) => update('business_type', value)}
          />
        </ReviewSection>

        <ReviewSection
          title="Where they buy it"
          className="border-border-subtle border-t md:border-t-0 md:border-l md:pl-4"
        >
          <RadioGroup
            variant="chip"
            ariaLabel="Where they buy it"
            value={profile.market_scope === 'local' ? 'regional' : profile.market_scope}
            options={MARKET_SCOPE_CHOICES}
            onValueChange={(value) => update('market_scope', value)}
          />
        </ReviewSection>
      </div>
    </div>
  );
}
