'use client';

import { Field } from '@/components/ui/field';
import { Input, Textarea } from '@/components/ui/input';
import type { DiscoveryProfile } from '@/lib/api/brand-discoveries';

export function hasConfirmedIcp(profile: DiscoveryProfile | null): profile is DiscoveryProfile {
  return Boolean(
    profile?.positioning.trim() &&
      profile.target_audience.trim() &&
      profile.products_services.some((item) => item.trim()),
  );
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

  return (
    <section className="border-border-subtle bg-well/40 space-y-4 rounded-xl border p-4">
      <div className="space-y-1">
        <h2 className="website-small-heading text-foreground">Confirm your ICP</h2>
        <p className="website-body text-muted">
          These facts shape the questions CiteLadder creates. Review or edit them before generation.
        </p>
      </div>
      <Field label="Positioning" required>
        {(props) => (
          <Textarea
            {...props}
            value={profile.positioning}
            onChange={(event) => update('positioning', event.target.value)}
            placeholder="How your offer is positioned"
          />
        )}
      </Field>
      <Field label="Target audience" required>
        {(props) => (
          <Input
            {...props}
            value={profile.target_audience}
            onChange={(event) => update('target_audience', event.target.value)}
            placeholder="Who is making the buying decision?"
          />
        )}
      </Field>
      <Field label="Products and services" required>
        {(props) => (
          <Input
            {...props}
            value={profile.products_services.join(', ')}
            onChange={(event) =>
              update(
                'products_services',
                event.target.value
                  .split(',')
                  .map((item) => item.trim())
                  .filter(Boolean),
              )
            }
            placeholder="Analytics software, attribution reporting"
          />
        )}
      </Field>
      <Field label="Description">
        {(props) => (
          <Textarea
            {...props}
            value={profile.description}
            onChange={(event) => update('description', event.target.value)}
            placeholder="A short factual description"
          />
        )}
      </Field>
    </section>
  );
}
