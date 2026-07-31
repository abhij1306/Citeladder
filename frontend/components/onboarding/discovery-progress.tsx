'use client';

import { AlertTriangle, Check, Globe, Loader2, MessageSquare, Sparkles, Users } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { DiscoveryState, SectionStatus } from '@/lib/onboarding/use-discovery';

/**
 * The discovery step's on-screen progress.
 *
 * Three rows, one per parallel call, each resolving independently — the point
 * of the animation is to make "we are doing three things for you" legible while
 * the calls are in flight.
 */
const ROWS = [
  {
    key: 'domains',
    icon: Globe,
    label: 'Your domains',
    subLabel: 'Auto-detecting web presence and brand aliases',
  },
  {
    key: 'competitors',
    icon: Users,
    label: 'Competitors',
    subLabel: 'Identifying direct category rivals in AI responses',
  },
  {
    key: 'prompts',
    icon: MessageSquare,
    label: 'Starting prompts',
    subLabel: 'Generating high-intent buyer search prompts',
  },
] as const;

function statusText(status: SectionStatus, count: number, unconfigured: boolean) {
  if (status === 'error') return unconfigured ? 'Not available' : 'Failed';
  if (status === 'done') return count === 0 ? 'Nothing found' : `${count} discovered`;
  return 'AI Searching…';
}

export function DiscoveryProgress({
  state,
  onRetry,
}: Readonly<{
  state: DiscoveryState;
  onRetry: (key: 'domains' | 'competitors' | 'prompts') => void;
}>) {
  return (
    <ul className="grid list-none gap-3 p-0">
      {ROWS.map((row) => {
        const section = state[row.key];
        const count = section.data.length;
        const done = section.status === 'done';
        const failed = section.status === 'error';
        const searching = section.status === 'loading' || section.status === 'idle';

        return (
          <li
            key={row.key}
            className={cn(
              'relative overflow-hidden rounded-xl border p-4 transition-colors duration-300',
              done
                ? 'border-success-border/60 bg-success-bg/30'
                : failed
                  ? 'border-danger-border/60 bg-danger-bg/30'
                  : 'border-accent-border/40 bg-white',
            )}
          >
            <div className="flex items-center gap-4">
              <div
                className={cn(
                  'flex size-10 shrink-0 items-center justify-center rounded-lg border transition-colors duration-300',
                  done
                    ? 'border-success-border/60 bg-success-bg/80 text-success-text'
                    : failed
                      ? 'border-danger-border/60 bg-danger-bg/80 text-danger-text'
                      : 'border-accent-border/80 bg-accent-soft text-accent-text',
                )}
              >
                <row.icon className="size-5" strokeWidth={1.75} aria-hidden />
              </div>

              <div className="min-w-0 flex-1 space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className="text-foreground text-sm font-semibold">{row.label}</span>
                  {searching && (
                    <span className="text-3xs bg-accent-soft text-accent-text inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium">
                      <Sparkles
                        className="size-3 animate-spin motion-reduce:animate-none"
                        aria-hidden
                      />{' '}
                      AI Active
                    </span>
                  )}
                </div>
                <p className="text-muted text-xs">{row.subLabel}</p>
              </div>

              <div className="flex shrink-0 items-center gap-3">
                <span
                  className={cn(
                    'text-xs font-medium',
                    failed
                      ? 'text-danger-text'
                      : done
                        ? 'text-success-text font-semibold'
                        : 'text-accent-text',
                  )}
                  role="status"
                >
                  {statusText(section.status, count, section.unconfigured)}
                </span>

                {failed ? (
                  <div className="bg-danger-bg text-danger-text flex size-6 items-center justify-center rounded-full">
                    <AlertTriangle className="size-4" aria-hidden />
                  </div>
                ) : done ? (
                  <div className="bg-success flex size-6 items-center justify-center rounded-full text-white">
                    <Check className="size-4" strokeWidth={2.5} aria-hidden />
                  </div>
                ) : (
                  <div className="bg-accent-soft text-accent-text flex size-6 items-center justify-center rounded-full">
                    <Loader2
                      className="size-4 animate-spin motion-reduce:animate-none"
                      aria-hidden
                    />
                  </div>
                )}

                {failed && !section.unconfigured ? (
                  <Button variant="ghost" size="sm" onClick={() => onRetry(row.key)}>
                    Retry
                  </Button>
                ) : null}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
