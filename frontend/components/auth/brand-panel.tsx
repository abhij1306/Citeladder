import Link from 'next/link';

import { LogoMark } from '@/components/ui/logo-mark';
import { cn } from '@/lib/utils';

export function AuthWordmark({ compact = false, light = false }: Readonly<{ compact?: boolean; light?: boolean }>) {
  return (
    <Link
      href="/"
      aria-label="CiteLadder home"
      className="group inline-flex items-center gap-3 no-underline transition-opacity hover:opacity-90"
    >
      <span className="text-accent inline-flex shrink-0">
        <LogoMark size={compact ? 22 : 28} />
      </span>
      <span
        className={cn(
          'font-display font-semibold tracking-tight',
          light ? 'text-white' : 'text-foreground',
          compact ? 'text-lg' : 'text-xl',
        )}
      >
        CiteLadder
      </span>


    </Link>
  );
}



export function AuthBrandPanel() {
  return (
    <div className="bg-slate-950 relative col-span-1 flex min-h-full flex-col items-center justify-center overflow-hidden px-8 py-12 text-white max-[900px]:hidden">
      {/* Dark ambient background glow */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="bg-radial from-blue-900/20 via-slate-950/80 to-slate-950 absolute -top-1/4 -left-1/4 size-[150%] rounded-full blur-3xl" />
        <div className="bg-blue-600/10 absolute top-1/2 left-1/2 size-96 -translate-x-1/2 -translate-y-1/2 rounded-full blur-[100px]" />
        {/* Abstract dark ribbon lines */}
        <div className="border-slate-800/40 absolute top-1/3 -left-20 h-96 w-[600px] -rotate-12 rounded-[100px] border-2" />
        <div className="border-slate-800/30 absolute top-1/4 -left-10 h-96 w-[650px] -rotate-12 rounded-[120px] border" />
      </div>

      {/* Centered Brand Mark & Wordmark */}
      <div className="relative z-10 flex items-center justify-center">
        <AuthWordmark light />
      </div>
    </div>
  );
}


