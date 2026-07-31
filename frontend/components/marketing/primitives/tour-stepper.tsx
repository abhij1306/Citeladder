import type { ElementType } from 'react';
import { Pause, Play } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface TourStepItem {
  id: string;
  label: string;
  icon: ElementType;
}

/**
 * Shared tour stepper component rendered in ProductWindow.
 */
export function TourStepper({
  steps,
  activeStep,
  isPlaying,
  onSelectStep,
  onTogglePlay,
  className,
  compact = false,
}: Readonly<{
  steps: readonly TourStepItem[];
  activeStep: number;
  isPlaying: boolean;
  onSelectStep: (index: number) => void;
  onTogglePlay: () => void;
  className?: string;
  compact?: boolean;
}>) {
  return (
    <div
      className={cn(
        'flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between',
        className,
      )}
    >
      <div className="grid grid-cols-2 gap-1.5 sm:flex sm:items-center sm:gap-2">
        {steps.map((step, idx) => {
          const Icon = step.icon;
          const isActive = idx === activeStep;
          return (
            <button
              key={step.id}
              type="button"
              aria-pressed={isActive}
              onClick={() => onSelectStep(idx)}
              className={cn(
                'text-mkt-meta flex items-center gap-2 rounded-lg px-3 py-2 text-left font-semibold transition-colors',
                compact && 'gap-1.5 rounded-md px-3 py-1.5',
                isActive
                  ? 'bg-mkt-accent text-white'
                  : 'bg-mkt-surface text-mkt-ink-soft hover:text-mkt-ink',
              )}
            >
              <Icon
                aria-hidden
                className={cn(
                  'size-4 shrink-0',
                  compact && 'size-3',
                  isActive ? 'text-white' : 'text-mkt-proof',
                )}
              />
              <span className="truncate">{step.label}</span>
            </button>
          );
        })}
      </div>

      <div className="border-mkt-line-soft flex items-center justify-between gap-2 border-t pt-1.5 sm:justify-end sm:border-t-0 sm:pt-0">
        <span className="text-mkt-meta text-mkt-ink-muted font-mono font-medium">
          {activeStep + 1} / {steps.length}
        </span>
        <button
          type="button"
          onClick={onTogglePlay}
          aria-pressed={isPlaying}
          aria-label={isPlaying ? 'Pause story tour' : 'Play story tour'}
          className="border-mkt-line-soft text-mkt-ink-soft bg-mkt-surface hover:text-mkt-ink rounded-md border p-1"
          title={isPlaying ? 'Pause story tour' : 'Play story tour'}
        >
          {isPlaying ? (
            <Pause className="size-3" aria-hidden />
          ) : (
            <Play className="size-3" aria-hidden />
          )}
        </button>
      </div>
    </div>
  );
}
