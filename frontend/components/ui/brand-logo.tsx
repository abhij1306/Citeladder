'use client';

import Image from 'next/image';
import { useState } from 'react';

import { logoDevUrl } from '@/lib/brand/logo-dev';
import { brandInitials } from '@/lib/brand/initials';
import { cn } from '@/lib/utils';

const SIZE = {
  xs: { pixels: 14, className: 'size-3.5 rounded-xs text-xs' },
  sm: { pixels: 20, className: 'size-5 rounded text-xs' },
  md: { pixels: 24, className: 'size-6 rounded-md text-xs' },
  lg: { pixels: 32, className: 'size-8 rounded-md text-sm' },
  xl: { pixels: 40, className: 'size-10 rounded-lg text-base' },
} as const;

/**
 * One brand-avatar treatment everywhere, with a three-step fallback:
 * our own cached favicon → Logo.dev's CDN → deterministic initials.
 *
 * The cached asset comes first because it is the real icon, served same-origin
 * from our database. Logo.dev covers the sites that refuse *our* crawler
 * (bot-blocking WAFs), which is a gap no crawler improvement can close. Each
 * step is entered only when the previous image actually fails to load, so a
 * working logo never costs a third-party request.
 *
 * Decorative: the adjacent brand name carries the accessible label.
 */
export function BrandLogo({
  name,
  logoUrl,
  websiteUrl,
  size = 'sm',
  className,
}: Readonly<{
  name: string;
  logoUrl?: string | null;
  /** Brand site, used to derive the Logo.dev fallback. */
  websiteUrl?: string | null;
  size?: keyof typeof SIZE;
  className?: string;
}>) {
  const [failed, setFailed] = useState<Record<string, true>>({});
  const spec = SIZE[size];

  const cached = logoUrl && !failed[logoUrl] ? logoUrl : null;
  const remote = logoDevUrl(websiteUrl, spec.pixels);
  // Only reach for the CDN once the cached asset is gone or has failed.
  const src = cached ?? (remote && !failed[remote] ? remote : null);

  return (
    <span
      aria-hidden
      className={cn(
        'bg-accent-soft text-accent-text relative grid shrink-0 place-items-center overflow-hidden font-medium uppercase',
        spec.className,
        className,
      )}
    >
      {src ? (
        <Image
          // Keyed by src so swapping sources remounts the element; without it
          // React reuses the <img> and a cached error state can suppress the
          // load event for the replacement.
          key={src}
          src={src}
          alt=""
          width={spec.pixels}
          height={spec.pixels}
          unoptimized
          className="bg-panel size-full object-contain p-[2px]"
          onError={() => setFailed((prev) => ({ ...prev, [src]: true }))}
        />
      ) : (
        brandInitials(name)
      )}
    </span>
  );
}
