'use client';

import { Eye, EyeOff, Lock, Mail, type LucideIcon } from 'lucide-react';
import Link from 'next/link';
import { type ComponentProps, type ReactNode, useState } from 'react';

import { Button } from '@/components/marketing/primitives/button';
import { Alert as MktAlert } from '@/components/ui/alert';
import { Field as MktField } from '@/components/ui/field';
import { Input as MktInput } from '@/components/ui/input';

type InputProps = ComponentProps<typeof MktInput>;

export function AuthEmailField({
  error,
  inputProps,
}: Readonly<{ error?: string; inputProps: InputProps }>) {
  return (
    <MktField label="Email" required error={error}>
      {(props) => (
        <div className="relative">
          <MktInput
            {...props}
            {...inputProps}
            type="email"
            autoComplete="email"
            spellCheck={false}
            placeholder="you@company.com"
            className="border-border-subtle bg-background-alt text-foreground placeholder:text-muted focus:border-accent focus:ring-accent-border focus:bg-panel pl-10"
          />
          <Mail
            aria-hidden
            className="text-muted pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
          />
        </div>
      )}
    </MktField>
  );
}

export function AuthPasswordField({
  label,
  error,
  inputProps,
  autoComplete,
  placeholder,
  visibilityLabel = label,
}: Readonly<{
  label: string;
  error?: string;
  inputProps: InputProps;
  autoComplete: 'current-password' | 'new-password';
  placeholder: string;
  visibilityLabel?: string;
}>) {
  const [visible, setVisible] = useState(false);
  return (
    <MktField label={label} required error={error}>
      {(props) => (
        <div className="relative">
          <MktInput
            {...props}
            {...inputProps}
            type={visible ? 'text' : 'password'}
            autoComplete={autoComplete}
            placeholder={placeholder}
            className="border-border-subtle bg-background-alt text-foreground placeholder:text-muted focus:border-accent focus:ring-accent-border focus:bg-panel pr-10 pl-10"
          />
          <Lock
            aria-hidden
            className="text-muted pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
          />
          <button
            type="button"
            onClick={() => setVisible((current) => !current)}
            className="text-muted hover:text-muted absolute top-1/2 right-3 -translate-y-1/2 p-1 transition-colors"
            aria-label={`${visible ? 'Hide' : 'Show'} ${visibilityLabel}`}
          >
            {visible ? (
              <EyeOff className="size-4" aria-hidden />
            ) : (
              <Eye className="size-4" aria-hidden />
            )}
          </button>
        </div>
      )}
    </MktField>
  );
}

export function AuthFormShell({
  icon: Icon,
  title,
  description,
  error,
  onSubmit,
  pending,
  submitLabel,
  pendingLabel,
  footerPrompt,
  footerHref,
  footerLabel,
  children,
}: Readonly<{
  icon: LucideIcon;
  title: string;
  description: string;
  error?: string;
  onSubmit: ComponentProps<'form'>['onSubmit'];
  pending: boolean;
  submitLabel: string;
  pendingLabel: string;
  footerPrompt: string;
  footerHref: string;
  footerLabel: string;
  children: ReactNode;
}>) {
  return (
    <div className="relative">
      <div className="bg-panel shadow-card relative rounded-2xl p-8 sm:p-10">
        <div className="mb-8 space-y-2 text-center sm:text-left">
          <div className="border-accent-border bg-background-alt text-accent-text mb-2 inline-flex size-10 items-center justify-center rounded-xl border">
            <Icon className="size-5" aria-hidden />
          </div>
          <h1 className="font-display text-foreground text-2xl font-medium sm:text-3xl">{title}</h1>
          <p className="text-muted text-sm">{description}</p>
        </div>
        {error ? (
          <div className="mb-6">
            <MktAlert>{error}</MktAlert>
          </div>
        ) : null}
        <form noValidate onSubmit={onSubmit} className="grid gap-5">
          {children}
          <Button type="submit" className="mt-2 w-full font-medium" disabled={pending}>
            {pending ? pendingLabel : submitLabel}
          </Button>
        </form>
        <p className="text-muted mt-8 text-center text-sm font-medium">
          {footerPrompt}{' '}
          <Link
            href={footerHref}
            className="text-accent-text hover:text-accent-text font-medium transition-colors"
          >
            {footerLabel}
          </Link>
        </p>
      </div>
    </div>
  );
}
