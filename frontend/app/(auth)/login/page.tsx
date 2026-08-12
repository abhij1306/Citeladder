'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { useForm } from 'react-hook-form';

import { AuthEmailField, AuthFormShell, AuthPasswordField } from '@/components/auth/auth-form';
import { authApi } from '@/lib/api/auth';
import { authErrorMessage, loginFormSchema, type LoginFormValues } from '@/lib/auth/forms';
import { useAuthMutation } from '@/lib/auth/use-auth-mutation';

function LoginForm() {
  const searchParams = useSearchParams();
  const description =
    searchParams.get('registered') === '1'
      ? 'Your account is ready. Sign in to continue.'
      : 'Welcome back! Please sign in to continue.';
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

  return (
    <AuthFormShell
      title="Sign in"
      description={description}
      error={mutation.isError ? authErrorMessage(mutation.error) : undefined}
      onSubmit={handleSubmit(submit)}
      pending={isSubmitting || mutation.isPending}
      submitLabel="Continue"
      pendingLabel="Signing in…"
      footerPrompt="Don't have an account?"
      footerHref="/register"
      footerLabel="Sign up"
    >
      <AuthEmailField error={errors.email?.message} inputProps={register('email')} />
      <AuthPasswordField
        label="Password"
        error={errors.password?.message}
        inputProps={register('password')}
        autoComplete="current-password"
        placeholder="••••••••"
      />
    </AuthFormShell>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
