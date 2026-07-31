'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Eye, EyeOff, Lock, Mail } from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';
import { useForm } from 'react-hook-form';

import { Button } from '@/components/marketing/primitives/button';
import { MktAlert, MktField, MktInput } from '@/components/marketing/primitives/field';
import { authApi } from '@/lib/api/auth';
import { authErrorMessage, loginFormSchema, type LoginFormValues } from '@/lib/auth/forms';
import { useAuthMutation } from '@/lib/auth/use-auth-mutation';

/**
 * Login page. react-hook-form + zod client validation; on success the `me`
 * cache is primed and the user is routed directly to `/onboarding` (no
 * projects yet) or `/projects`. Email is the only sign-in path.
 */
export default function LoginPage() {
  const [showPassword, setShowPassword] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginFormSchema),
    defaultValues: { email: '', password: '' },
  });

  const { mutation, submit } = useAuthMutation((values: LoginFormValues) =>
    authApi.login(values.email, values.password),
  );

  const onSubmit = handleSubmit(submit);
  const pending = isSubmitting || mutation.isPending;

  return (
    <div className="relative">
      <div className="shadow-card border-mkt-line-soft relative rounded-2xl border bg-white p-8 sm:p-10">
        <div className="mb-8 space-y-2 text-center sm:text-left">
          <div className="border-mkt-proof-line/30 bg-mkt-wash text-mkt-proof mb-2 inline-flex size-10 items-center justify-center rounded-xl border">
            <Lock className="size-5" />
          </div>
          <h1 className="font-mkt-display text-mkt-ink text-2xl font-bold sm:text-3xl">Sign in</h1>
          <p className="text-mkt-ink-muted text-sm">Pick up where your brand left off.</p>
        </div>

        {mutation.isError ? (
          <div className="mb-6">
            <MktAlert>{authErrorMessage(mutation.error)}</MktAlert>
          </div>
        ) : null}

        <form noValidate onSubmit={onSubmit} className="grid gap-5">
          <MktField label="Email" required error={errors.email?.message}>
            {(props) => (
              <div className="relative">
                <MktInput
                  {...props}
                  {...register('email')}
                  type="email"
                  autoComplete="email"
                  placeholder="you@company.com"
                  className="border-mkt-line-soft bg-mkt-paper-raised/80 text-mkt-ink placeholder:text-mkt-ink-muted focus:border-mkt-proof focus:ring-mkt-proof/20 pl-10 focus:bg-white"
                />
                <Mail className="text-mkt-ink-muted pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
              </div>
            )}
          </MktField>

          <MktField label="Password" required error={errors.password?.message}>
            {(props) => (
              <div className="relative">
                <MktInput
                  {...props}
                  {...register('password')}
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  className="border-mkt-line-soft bg-mkt-paper-raised/80 text-mkt-ink placeholder:text-mkt-ink-muted focus:border-mkt-proof focus:ring-mkt-proof/20 pr-10 pl-10 focus:bg-white"
                />
                <Lock className="text-mkt-ink-muted pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
                <button
                  type="button"
                  onClick={() => setShowPassword((prev) => !prev)}
                  className="text-mkt-ink-muted hover:text-mkt-ink-soft absolute top-1/2 right-3 -translate-y-1/2 p-1 transition-colors"
                  aria-label={showPassword ? 'Hide value' : 'Show value'}
                >
                  {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            )}
          </MktField>

          <Button type="submit" className="mt-2 w-full font-semibold" disabled={pending}>
            {pending ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>

        {/* Footer link - No separating line */}
        <p className="text-mkt-ink-soft mt-8 text-center text-sm font-medium">
          Don&apos;t have an account?{' '}
          <Link
            href="/register"
            className="text-mkt-proof hover:text-mkt-proof-hover font-semibold transition-colors"
          >
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}
