import type { ComponentPropsWithoutRef, Ref } from 'react';

import { cn } from '@/lib/utils';

const textareaClasses =
  'focus-ring min-h-24 w-full resize-y rounded-[var(--radius-control)] border border-border-strong/80 bg-input p-2.5 text-sm text-foreground transition-[border-color,box-shadow] placeholder:text-muted hover:border-border-bold focus:border-accent aria-invalid:border-danger disabled:cursor-not-allowed disabled:opacity-50';

export function Textarea({
  className,
  ref,
  ...props
}: Readonly<ComponentPropsWithoutRef<'textarea'> & { ref?: Ref<HTMLTextAreaElement> }>) {
  return <textarea ref={ref} className={cn(textareaClasses, className)} {...props} />;
}
