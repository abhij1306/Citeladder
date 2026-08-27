import type { ComponentPropsWithoutRef } from 'react';

import { availabilityLabel, type DataAvailabilityState } from '@/lib/format';
import { cn } from '@/lib/utils';

/** Compact, explicit presentation for a product value that is not available as a number. */
export function UnavailableValue({
  state,
  className,
  ...props
}: Readonly<
  Omit<ComponentPropsWithoutRef<'span'>, 'children'> & {
    state: DataAvailabilityState;
  }
>) {
  return (
    <span {...props} className={cn('value-placeholder font-sans text-xs font-medium', className)}>
      {availabilityLabel(state)}
    </span>
  );
}
