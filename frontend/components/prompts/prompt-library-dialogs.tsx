import type { Dispatch, SetStateAction } from 'react';

import type { PromptGenerateInput, PromptInput } from '@/lib/api/prompts';
import type { Prompt, PromptGenerateResponse, Topic } from '@/lib/api/types';

import { CsvImportDialog } from './csv-import-dialog';
import { GeneratePromptsDialog } from './generate-prompts-dialog';
import { PromptFormDialog } from './prompt-form-dialog';

type PromptLibraryDialogsProps = {
  formOpen: boolean;
  setFormOpen: Dispatch<SetStateAction<boolean>>;
  editing: Prompt | undefined;
  setEditing: Dispatch<SetStateAction<Prompt | undefined>>;
  submitForm: (input: PromptInput) => Promise<void>;
  isSaving: boolean;
  formError?: string;
  importOpen: boolean;
  setImportOpen: Dispatch<SetStateAction<boolean>>;
  importPrompts: (rows: PromptInput[]) => Promise<void>;
  isImporting: boolean;
  importError?: string;
  generateOpen: boolean;
  setGenerateOpen: Dispatch<SetStateAction<boolean>>;
  topics: Topic[];
  selectedTopicId: string | null;
  generatePrompts: (input: PromptGenerateInput) => Promise<void>;
  isGenerating: boolean;
  generateError?: unknown;
  generateResult: PromptGenerateResponse | null;
};

export function PromptLibraryDialogs({
  formOpen,
  setFormOpen,
  editing,
  setEditing,
  submitForm,
  isSaving,
  formError,
  importOpen,
  setImportOpen,
  importPrompts,
  isImporting,
  importError,
  generateOpen,
  setGenerateOpen,
  topics,
  selectedTopicId,
  generatePrompts,
  isGenerating,
  generateError,
  generateResult,
}: Readonly<PromptLibraryDialogsProps>) {
  return (
    <>
      <PromptFormDialog
        open={formOpen}
        onOpenChange={(open) => {
          setFormOpen(open);
          if (!open) setEditing(undefined);
        }}
        prompt={editing}
        onSubmit={submitForm}
        isSaving={isSaving}
        error={formError}
      />
      <CsvImportDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        onImport={importPrompts}
        isImporting={isImporting}
        error={importError}
      />
      <GeneratePromptsDialog
        open={generateOpen}
        onOpenChange={setGenerateOpen}
        topics={topics}
        defaultTopicId={selectedTopicId}
        onGenerate={generatePrompts}
        isGenerating={isGenerating}
        error={generateError}
        result={generateResult}
      />
    </>
  );
}
