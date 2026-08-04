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
        'flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between',
        className,
      )}
    >
      <div className="grid grid-cols-2 gap-2 sm:flex sm:items-center sm:gap-3">
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
                'flex items-center gap-3 rounded-lg px-4 py-3 text-left text-xs font-semibold transition-colors',
                compact && 'gap-2 rounded-md px-4 py-2',
                isActive ? 'bg-accent text-white' : 'bg-panel text-muted hover:text-foreground',
              )}
            >
              <Icon
                aria-hidden
                className={cn(
                  'size-4 shrink-0',
                  compact && 'size-3',
                  isActive ? 'text-white' : 'text-accent-text',
                )}
              />
              <span className="truncate">{step.label}</span>
            </button>
          );
        })}
      </div>

      <div className="border-border-subtle flex items-center justify-between gap-3 border-t pt-2 sm:justify-end sm:border-t-0 sm:pt-0">
        <span className="text-muted font-mono text-xs font-medium">
          {activeStep + 1} / {steps.length}
        </span>
        <button
          type="button"
          onClick={onTogglePlay}
          aria-pressed={isPlaying}
          aria-label={isPlaying ? 'Pause story tour' : 'Play story tour'}
          className="border-border-subtle text-muted bg-panel hover:text-foreground rounded-md border p-2"
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
