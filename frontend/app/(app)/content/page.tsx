'use client';

import { ContentScreen } from '@/components/content/content-screen';
import { useSearchParams } from 'next/navigation';

/**
 * Content screen (sidebar "Content", Actions group).
 *
 * Prompt-box-first AI content generation grounded in the project's crawled
 * website evidence: describe the page, optionally include Website context,
 * generate, and copy the sanitised Markdown result. History lists recent
 * generations for the active project. The page title renders in the top bar
 * (F5), so there is no in-page header.
 */
export default function ContentPage() {
  const searchParams = useSearchParams();
  const opportunityId = searchParams.get('opportunity_id');
  return (
    <div className="grid gap-6">
      <ContentScreen opportunityId={opportunityId} />
    </div>
  );
}
