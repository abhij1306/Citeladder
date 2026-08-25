import Image from 'next/image';

const LOGO_ASPECT_RATIO = 1182 / 205;

/** The canonical CiteLadder logo lockup. */
export function LogoMark({ size = 16 }: Readonly<{ size?: number }>) {
  return (
    <span
      className="inline-flex shrink-0 overflow-hidden rounded-xs"
      style={{ width: size * LOGO_ASPECT_RATIO, height: size }}
      aria-hidden="true"
    >
      <Image
        src="/citeladder-logo.webp"
        alt=""
        width={1182}
        height={205}
        className="size-full object-contain"
      />
    </span>
  );
}
