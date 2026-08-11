import { useId } from 'react';

/** A rounded inverted L with one central step line. */
export function LogoMark({ size = 16 }: Readonly<{ size?: number }>) {
  const depthFilterId = useId().replaceAll(':', '');

  return (
    <span className="logo-mark" style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 24 24">
        <defs>
          <filter id={depthFilterId} x="-25%" y="-25%" width="150%" height="150%">
            <feGaussianBlur in="SourceAlpha" stdDeviation="0.6" result="outer-blur" />
            <feOffset in="outer-blur" dx="0.8" dy="0.8" result="outer-offset" />
            <feFlood
              floodColor="var(--color-foreground)"
              floodOpacity="0.28"
              result="outer-color"
            />
            <feComposite in="outer-color" in2="outer-offset" operator="in" result="outer-shadow" />
            <feComponentTransfer in="SourceAlpha" result="inverse-alpha">
              <feFuncA type="table" tableValues="1 0" />
            </feComponentTransfer>
            <feGaussianBlur in="inverse-alpha" stdDeviation="0.65" result="inner-blur" />
            <feOffset in="inner-blur" dx="0.65" dy="0.65" result="inner-offset" />
            <feComposite in="inner-offset" in2="SourceAlpha" operator="in" result="inner-mask" />
            <feFlood
              floodColor="var(--color-foreground)"
              floodOpacity="0.24"
              result="inner-color"
            />
            <feComposite in="inner-color" in2="inner-mask" operator="in" result="inner-shadow" />
            <feMerge>
              <feMergeNode in="outer-shadow" />
              <feMergeNode in="SourceGraphic" />
              <feMergeNode in="inner-shadow" />
            </feMerge>
          </filter>
        </defs>
        <g filter={`url(#${depthFilterId})`}>
          <path
            d="M4 20h16V4"
            style={{ fill: 'none' }}
            stroke="currentColor"
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M10 10h10"
            style={{ fill: 'none' }}
            stroke="currentColor"
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
      </svg>
    </span>
  );
}
