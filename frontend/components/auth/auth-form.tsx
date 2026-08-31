'use client';

import { Eye, EyeOff } from 'lucide-react';
import Link from 'next/link';
import { type ComponentProps, type ReactNode, useState } from 'react';

import { Alert as MktAlert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pressable } from '@/components/ui/pressable';
import { authApi } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/errors';
import { assignLocation } from '@/lib/navigate';

type InputProps = ComponentProps<typeof Input>;

function GoogleIcon({ className = 'size-4 shrink-0' }: Readonly<{ className?: string }>) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <path
        fill="var(--color-brand-google-blue)"
        d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3h3.86c2.26-2.09 3.68-5.17 3.68-9.12z"
      />
      <path
        fill="var(--color-brand-google-green)"
        d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.29v3.09C3.26 21.3 7.31 24 12 24z"
      />
      <path
        fill="var(--color-brand-google-yellow)"
        d="M5.27 14.29c-.25-.72-.38-1.49-.38-2.29s.14-1.57.38-2.29V6.62H1.29C.47 8.24 0 10.06 0 12s.47 3.76 1.29 5.38l3.98-3.09z"
      />
      <path
        fill="var(--color-brand-google-red)"
        d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.31 0 3.26 2.7 1.29 6.62l3.98 3.09C6.22 6.86 8.87 4.75 12 4.75z"
      />
    </svg>
  );
}

export function AuthEmailField({
  error,
  inputProps,
}: Readonly<{ error?: string; inputProps: InputProps }>) {
  return (
    <Field label="Email address" required error={error}>
      {(props) => (
        <Input
          {...props}
          {...inputProps}
          type="email"
          autoComplete="email"
          spellCheck={false}
          placeholder="hello@app.com"
          size="lg"
        />
      )}
    </Field>
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
    <Field label={label} required error={error}>
      {(props) => (
        <Input
          {...props}
          {...inputProps}
          type={visible ? 'text' : 'password'}
          autoComplete={autoComplete}
          placeholder={placeholder}
          size="lg"
          endContent={
            <Pressable
              type="button"
              onClick={() => setVisible((current) => !current)}
              className="text-muted hover:text-foreground grid size-7 place-items-center rounded-[var(--radius-control)] transition-colors"
              aria-label={`${visible ? 'Hide' : 'Show'} ${visibilityLabel}`}
            >
              {visible ? (
                <EyeOff className="size-4" aria-hidden />
              ) : (
                <Eye className="size-4" aria-hidden />
              )}
            </Pressable>
          }
        />
      )}
    </Field>
  );
}

export function AuthFormShell({
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
  showOAuth = true,
  children,
}: Readonly<{
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
  showOAuth?: boolean;
  children: ReactNode;
}>) {
  const [oauthNotice, setOauthNotice] = useState<string | null>(null);
  const [oauthPending, setOauthPending] = useState(false);

  async function handleGoogleSignIn() {
    // The button stays live for the whole round trip otherwise, and a second
    // click starts a second authorization before the first can redirect.
    if (oauthPending) return;
    setOauthPending(true);
    setOauthNotice(null);
    try {
      const { authorize_url } = await authApi.oauthStart('google');
      assignLocation(authorize_url);
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setOauthNotice('Google sign-in is coming soon — please use email below.');
      } else {
        setOauthNotice('Unable to start Google sign-in. Please try email below.');
      }
    } finally {
      // Cleared even on the success path: `assignLocation` may be a no-op in a
      // test, and a permanently disabled button would strand the user.
      setOauthPending(false);
    }
  }

  return (
    <div className="w-full" data-auth-form>
      <div className="text-center">
        <h1 className="auth-form-title text-foreground">{title}</h1>
        <p className="website-body text-muted mt-1">{description}</p>
      </div>

      <div className="mt-6 space-y-4">
        {showOAuth && (
          <>
            <Button
              variant="secondary"
              size="lg"
              className="w-full gap-2 text-sm font-medium"
              disabled={oauthPending}
              onClick={() => void handleGoogleSignIn()}
            >
              <GoogleIcon />
              <span>{oauthPending ? 'Starting Google sign-in…' : 'Continue with Google'}</span>
            </Button>

            {oauthNotice ? <MktAlert>{oauthNotice}</MktAlert> : null}

            <div className="my-4 flex items-center gap-3">
              <span className="bg-border h-px flex-1" aria-hidden="true" />
              <span className="text-muted text-xs font-normal">or</span>
              <span className="bg-border h-px flex-1" aria-hidden="true" />
            </div>
          </>
        )}

        {error ? <MktAlert>{error}</MktAlert> : null}

        <form noValidate onSubmit={onSubmit} className="space-y-3">
          {children}

          <Button
            type="submit"
            size="lg"
            className="mt-2 w-full text-sm font-medium"
            disabled={pending}
          >
            {pending ? pendingLabel : submitLabel}
          </Button>
        </form>

        <p className="website-body text-muted pt-1 text-center">
          {footerPrompt}{' '}
          <Link
            href={footerHref}
            className="text-foreground hover:text-accent font-semibold transition-colors"
          >
            {footerLabel}
          </Link>
        </p>
      </div>
    </div>
  );
}
