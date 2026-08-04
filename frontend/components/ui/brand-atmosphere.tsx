import { cn } from '@/lib/utils';

export function BrandAtmosphere({
  variant = 'app',
  className,
}: Readonly<{ variant?: 'hero' | 'page' | 'app' | 'site'; className?: string }>) {
  return (
    <div aria-hidden className={cn('brand-atmosphere', `brand-atmosphere-${variant}`, className)}>
      <div className="brand-atmosphere-image" />
      <div className="brand-atmosphere-signal" />
    </div>
  );
}
