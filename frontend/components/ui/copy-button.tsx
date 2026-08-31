'use client';

import type { ComponentPropsWithoutRef } from 'react';
import { Check, Copy } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { Button } from './button';
import { useToast } from './toast';

export type CopyButtonProps = Omit<
  ComponentPropsWithoutRef<typeof Button>,
  'onClick' | 'pending'
> & {
  value: string;
  copiedLabel?: string;
  iconOnly?: boolean;
};

export function CopyButton({
  value,
  children = 'Copy',
  copiedLabel = 'Copied',
  iconOnly = false,
  ...props
}: Readonly<CopyButtonProps>) {
  const { notify } = useToast();
  const [status, setStatus] = useState<'idle' | 'copying' | 'copied' | 'error'>('idle');
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (resetTimer.current) clearTimeout(resetTimer.current);
    },
    [],
  );

  async function copy() {
    setStatus('copying');
    try {
      await navigator.clipboard.writeText(value);
      setStatus('copied');
      notify(copiedLabel);
      resetTimer.current = setTimeout(() => setStatus('idle'), 1800);
    } catch {
      setStatus('error');
    }
  }

  return (
    <Button
      variant="secondary"
      {...props}
      pending={status === 'copying'}
      onClick={() => void copy()}
      aria-live="polite"
      aria-label={iconOnly ? (status === 'copied' ? copiedLabel : 'Copy') : props['aria-label']}
    >
      {status === 'copied' ? (
        <Check className="size-4" aria-hidden />
      ) : (
        <Copy className="size-4" aria-hidden />
      )}
      {iconOnly
        ? null
        : status === 'copied'
          ? copiedLabel
          : status === 'error'
            ? 'Copy failed — retry'
            : children}
    </Button>
  );
}
