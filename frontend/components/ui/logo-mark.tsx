import Image from 'next/image';

const LOGOS = {
  light: { src: '/citeladder-logo.png', width: 1182, height: 205 },
  dark: { src: '/citeladder-dark-logo.webp', width: 1995, height: 327 },
} as const;

/** The canonical CiteLadder logo lockup. */
export function LogoMark({
  size = 16,
  surface = 'light',
}: Readonly<{ size?: number; surface?: keyof typeof LOGOS }>) {
  const logo = LOGOS[surface];

  return (
    <span
      className="inline-flex shrink-0 overflow-hidden rounded-xs"
      style={{ width: size * (logo.width / logo.height), height: size }}
      aria-hidden="true"
    >
      <Image
        src={logo.src}
        alt=""
        width={logo.width}
        height={logo.height}
        loading="eager"
        className="size-full object-contain"
      />
    </span>
  );
}
