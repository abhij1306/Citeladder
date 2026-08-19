import { useEffect, useState, type ReactNode } from 'react';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

export type PreviewProps = Readonly<{ phase: number; reduceMotion: boolean }>;

export const PRIMARY_SURFACE = 'border-border bg-panel shadow-elevated rounded-lg border';
export const SUPPORTING_SURFACE = 'border-border bg-background-alt shadow-card rounded-lg border';
export function ScreenHeader({
  icon,
  title,
  description,
  action,
}: Readonly<{ icon: ReactNode; title: string; description: string; action: ReactNode }>) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-3">
        <span className="bg-accent-soft text-accent-text grid size-9 shrink-0 place-items-center rounded-md">
          {icon}
        </span>
        <div>
          <h3 className="text-foreground text-base font-semibold">{title}</h3>
          <p className="text-muted mt-0.5 text-[13px] leading-relaxed">{description}</p>
        </div>
      </div>
      {action}
    </div>
  );
}

export function PreviewButton({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <span className="bg-accent text-inverse inline-flex h-8 items-center gap-1.5 rounded-sm px-3 text-[13px] font-medium shadow-xs">
      {children}
    </span>
  );
}

export function PreviewBadge({
  children,
  tone = 'neutral',
}: Readonly<{ children: ReactNode; tone?: 'neutral' | 'success' | 'warning' | 'info' }>) {
  if (tone === 'neutral') return <Badge>{children}</Badge>;
  return (
    <Badge variant="status" value={tone}>
      {children}
    </Badge>
  );
}

export function PhaseItem({
  visible,
  children,
  className,
}: Readonly<{
  visible: boolean;
  children: ReactNode;
  className?: string;
}>) {
  return <div className={cn(!visible && 'opacity-35', className)}>{children}</div>;
}

export function useTypedPreview(text: string, active: boolean, reduceMotion: boolean) {
  const [typed, setTyped] = useState('');
  useEffect(() => {
    if (reduceMotion || !active) return;
    let cursor = 0;
    const timer = window.setInterval(() => {
      cursor += 1;
      setTyped(text.slice(0, cursor));
      if (cursor >= text.length) window.clearInterval(timer);
    }, 24);
    return () => window.clearInterval(timer);
  }, [active, reduceMotion, text]);
  return reduceMotion || !active ? text : typed;
}

export function MetricStrip({
  items,
}: Readonly<{ items: ReadonlyArray<{ label: string; value: string; detail: string }> }>) {
  return (
    <div className="border-border bg-panel shadow-card mt-4 grid grid-cols-2 overflow-hidden rounded-md border lg:grid-cols-4">
      {items.map((item, index) => (
        <div
          key={item.label}
          className={cn(
            'px-3 py-2.5',
            index % 2 !== 0 && 'border-border-subtle border-l',
            index >= 2 && 'border-border-subtle border-t lg:border-t-0',
            index === 2 && 'lg:border-l',
          )}
        >
          <p className="text-subtle text-[11px] font-medium">{item.label}</p>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className="text-foreground text-base font-semibold tabular-nums">
              {item.value}
            </span>
            <span className="text-muted text-[10px]">{item.detail}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
