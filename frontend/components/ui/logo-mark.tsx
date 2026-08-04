/** Opposing citation forms advance upward as one compact CiteLadder mark. */
export function LogoMark({ size = 28 }: Readonly<{ size?: number }>) {
  return (
    <span className="logo-mark" style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 24 24" role="img">
        <path d="M3 4h9v4H7v5h5v4H3V4Zm18 16h-9v-4h5v-5h-5V7h9v13Z" />
      </svg>
    </span>
  );
}
