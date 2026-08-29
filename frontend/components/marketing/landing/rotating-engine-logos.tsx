import Image from 'next/image';

import { ENGINE_ROTOR_STAGGER_MS } from '@/lib/config/marketing';
import { cn } from '@/lib/utils';

import { EngineLogo, type OfficialEngineKey } from '../primitives/engine-logo';

type ExtendedLogoKey = 'grok' | 'copilot' | 'perplexity';
type LogoKey = OfficialEngineKey | ExtendedLogoKey;

const LOGO_PAIRS = [
  [
    { key: 'openai', label: 'ChatGPT' },
    { key: 'grok', label: 'Grok' },
  ],
  [
    { key: 'gemini', label: 'Gemini' },
    { key: 'copilot', label: 'Copilot' },
  ],
  [
    { key: 'claude', label: 'Claude' },
    { key: 'perplexity', label: 'Perplexity' },
  ],
] as const;

const EXTENDED_LOGOS: Record<
  Exclude<ExtendedLogoKey, 'grok'>,
  { path: string; viewBox: string }
> = {
  copilot: {
    viewBox: '0 0 1322.9 1147.5',
    path: 'M711.19 265.2c-27.333 0-46.933 3.07-58.8 9.33 27.067-80.267 47.6-210.13 168-210.13 114.93 0 108.4 138.27 157.87 200.8zm107.33 112.93c-35.467 125.2-70 251.2-110.13 375.33-12.133 36.4-45.733 61.6-84 61.6h-136.27c9.333-14 16.8-28.933 21.467-45.733 35.467-125.07 70-251.07 110.13-375.33 12.133-36.4 45.733-61.6 84-61.6h136.27c-9.333 14-16.8 28.934-21.467 45.734m-316.13 704.8c-114.93 0-108.4-138.13-157.87-200.67h267.07c27.467 0 47.067-3.07 58.8-9.33-27.067 80.266-47.6 210-168 210m777.47-758.93h.93c-32.667-38.266-82.267-57.866-146.67-57.866h-36.4c-34.533-2.8-65.333-26.134-76.533-58.8l-36.4-103.6C963.32 42 904.52 0 839.05 0H363.98C188.38 0 112.78 225.07 71.71 361.33 33.443 488.4-54.29 703.06 47.443 823.46c46.667 55.067 116.67 57.867 183.07 57.867 34.533 2.8 65.333 26.133 76.533 58.8l36.4 103.6c21.467 61.733 80.267 103.73 145.6 103.73h475.2c175.47 0 251.07-225.07 292.27-361.33 30.8-100.8 68.133-224.93 66.267-324.8 0-50.534-11.2-100-42.933-137.33Z',
  },
  perplexity: {
    viewBox: '0 0 24 24',
    path: 'M22.3977 7.0896h-2.3106V.0676l-7.5094 6.3542V.1577h-1.1554v6.1966L4.4904 0v7.0896H1.6023v10.3976h2.8882V24l6.932-6.3591v6.2005h1.1554v-6.0469l6.9318 6.1807v-6.4879h2.8882V7.0896zm-3.4657-4.531v4.531h-5.355l5.355-4.531zm-13.2862.0676 4.8691 4.4634H5.6458V2.6262zM2.7576 16.332V8.245h7.8476l-6.1149 6.1147v1.9723H2.7576zm2.8882 5.0404v-3.8852h.0001v-2.6488l5.7763-5.7764v7.0111l-5.7764 5.2993zm12.7086.0248-5.7766-5.1509V9.0618l5.7766 5.7766v6.5588zm2.8882-5.0652h-1.733v-1.9723L13.3948 8.245h7.8478v8.087z',
  },
};

function ProviderLogo({ logo }: Readonly<{ logo: LogoKey }>) {
  if (logo === 'openai' || logo === 'gemini' || logo === 'claude') {
    return (
      <EngineLogo
        engine={logo}
        className={cn(
          'size-7 shrink-0',
          logo === 'openai' && 'text-brand-openai',
          logo === 'gemini' && 'text-brand-gemini',
          logo === 'claude' && 'text-brand-claude',
        )}
      />
    );
  }
  if (logo === 'grok') {
    return (
      <Image
        src="/brand/grok.webp"
        alt=""
        width={30}
        height={30}
        className="size-7 shrink-0 object-contain"
      />
    );
  }
  const definition = EXTENDED_LOGOS[logo];
  if (logo === 'copilot') {
    return <CopilotLogo definition={definition} />;
  }
  return (
    <svg
      aria-hidden
      viewBox={definition.viewBox}
      className="text-brand-perplexity size-7 shrink-0 fill-current"
    >
      <path d={definition.path} />
    </svg>
  );
}

function CopilotLogo({ definition }: Readonly<{ definition: (typeof EXTENDED_LOGOS)['copilot'] }>) {
  return (
    <svg aria-hidden viewBox={definition.viewBox} className="size-7 shrink-0">
      <defs>
        <linearGradient id="copilot-brand-gradient" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--color-brand-copilot-violet)" />
          <stop offset="0.36" stopColor="var(--color-brand-copilot-blue)" />
          <stop offset="0.68" stopColor="var(--color-brand-copilot-cyan)" />
          <stop offset="1" stopColor="var(--color-brand-copilot-green)" />
        </linearGradient>
      </defs>
      <path d={definition.path} fill="url(#copilot-brand-gradient)" />
    </svg>
  );
}

function LogoFace({
  logo,
  alternate,
}: Readonly<{
  logo: (typeof LOGO_PAIRS)[number][number];
  alternate?: boolean;
}>) {
  return (
    <span className={cn('engine-rotor-face', alternate && 'engine-rotor-face-alternate')}>
      <ProviderLogo logo={logo.key} />
      <span className="text-foreground text-base font-medium">{logo.label}</span>
    </span>
  );
}

export function RotatingEngineLogos({ className }: Readonly<{ className?: string }>) {
  return (
    <div
      className={cn('engine-roster', className)}
      // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- This animated composite is one labelled image; img cannot contain its rendered logos.
      role="img"
      aria-label="ChatGPT, Grok, Gemini, Copilot, Claude and Perplexity."
    >
      <ul aria-hidden className="engine-roster-motion mx-auto grid max-w-2xl grid-cols-3 gap-3">
        {LOGO_PAIRS.map(([primary, alternate], index) => (
          <li key={primary.key} className="engine-rotor-slot">
            <span
              className="engine-rotor-inner"
              style={{ animationDelay: `${index * ENGINE_ROTOR_STAGGER_MS}ms` }}
            >
              <LogoFace logo={primary} />
              <LogoFace logo={alternate} alternate />
            </span>
          </li>
        ))}
      </ul>
      <ul aria-hidden className="engine-roster-static grid grid-cols-2 gap-2 sm:grid-cols-3">
        {LOGO_PAIRS.flat().map((logo) => (
          <li key={logo.key} className="engine-roster-static-item">
            <ProviderLogo logo={logo.key} />
            <span className="text-base font-medium">{logo.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
