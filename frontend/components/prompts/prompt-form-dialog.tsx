'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm } from 'react-hook-form';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input, Textarea } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import type { PromptInput } from '@/lib/api/prompts';
import type { Prompt } from '@/lib/api/types';
import {
  emptyPromptForm,
  formValuesToPromptInput,
  intentLabels,
  intentValues,
  promptFormSchema,
  promptToFormValues,
  type PromptFormValues,
} from '@/lib/prompts/forms';

/**
 * Add / edit prompt dialog (F7). react-hook-form + zod; the same form serves
 * create (no `prompt`) and edit (prefilled from `prompt`). Submit maps to the
 * API `PromptInput` and delegates persistence to `onSubmit`.
 */
export function PromptFormDialog({
  open,
  onOpenChange,
  prompt,
  onSubmit,
  isSaving,
  error,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  prompt?: Prompt;
  onSubmit: (input: PromptInput) => Promise<void> | void;
  isSaving?: boolean;
  error?: string;
}>) {
  const isEdit = Boolean(prompt);
  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<PromptFormValues>({
    resolver: zodResolver(promptFormSchema),
    values: prompt ? promptToFormValues(prompt) : emptyPromptForm,
  });

  const submit = handleSubmit(async (values) => {
    await onSubmit(formValuesToPromptInput(values));
  });

  const handleOpenChange = (next: boolean) => {
    if (!next) reset(prompt ? promptToFormValues(prompt) : emptyPromptForm);
    onOpenChange(next);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={handleOpenChange}
      title={isEdit ? 'Edit prompt' : 'Add prompt'}
      footer={
        <>
          <Button variant="ghost" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={isSaving}>
            {isSaving ? 'Saving…' : isEdit ? 'Save changes' : 'Add prompt'}
          </Button>
        </>
      }
    >
      <form noValidate onSubmit={submit} className="grid gap-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}

        <Field label="Prompt text" required error={errors.text?.message}>
          {(props) => (
            <Textarea
              {...props}
              {...register('text')}
              placeholder="What are the best running shoes for flat feet?"
            />
          )}
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Theme" error={errors.theme?.message} hint="Optional topic / category">
            {(props) => <Input {...props} {...register('theme')} placeholder="Comfort" />}
          </Field>
          <Field label="Intent" error={errors.intent?.message}>
            {(props) => (
              <Controller
                control={control}
                name="intent"
                render={({ field }) => (
                  <Select
                    {...props}
                    ariaLabel="Intent"
                    value={field.value}
                    onValueChange={field.onChange}
                    options={intentValues.map((value) => ({
                      value,
                      label: intentLabels[value],
                    }))}
                  />
                )}
              />
            )}
          </Field>
        </div>

        <div className="flex flex-wrap gap-[var(--workspace-gap)]">
          <Controller
            control={control}
            name="cohort"
            render={({ field }) => (
              <label className="text-foreground flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={field.value === 'comparison'}
                  onChange={(event) => field.onChange(event.target.checked ? 'comparison' : 'core')}
                  className="focus-ring accent-accent size-4 shrink-0"
                />
                Named comparison
              </label>
            )}
          />
          <Controller
            control={control}
            name="enabled"
            render={({ field }) => (
              <label className="text-foreground flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={field.value}
                  onChange={(event) => field.onChange(event.target.checked)}
                  className="focus-ring accent-accent size-4 shrink-0"
                />
                Enabled
              </label>
            )}
          />
        </div>
      </form>
    </Dialog>
  );
}
