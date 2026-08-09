import { segmentedItemVariants, segmentedTrackVariants } from './segmented-variants';

/**
 * Segmented track/pill recipes — the `bg-alt` track with a white (panel)
 * active pill used by small single-select SWITCHES (the trend card's metric
 * switch, the Sources card's Domains/URLs switch, the inventory section's
 * view switch).
 *
 * This is NOT the tab treatment: every `role=tablist` in the app renders the
 * ADS underline tablist from `components/ui/tabs.tsx`. The pill survives only
 * where two or three options act as a filter on the panel beneath rather
 * than as navigation between views.
 *
 * Exported as CLASS RECIPES rather than a component because the call sites
 * need different semantics on the same visual (a `radiogroup` in setup,
 * plain buttons for the chart switches). Sharing the classes keeps them
 * identical without forcing one ARIA role.
 */
export const segmentedTrackClasses = segmentedTrackVariants({});

export const segmentedItemClasses = (selected: boolean) => segmentedItemVariants({ selected });
