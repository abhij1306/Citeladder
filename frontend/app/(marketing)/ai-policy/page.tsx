import type { Metadata } from 'next';

import { LegalDocumentView } from '@/components/marketing/pages/legal';
import { AI_POLICY } from '@/lib/marketing-content/legal';

export const metadata: Metadata = {
  title: 'AI Policy',
  description: AI_POLICY.description,
  alternates: { canonical: '/ai-policy' },
};

export default function AiPolicyPage() {
  return <LegalDocumentView document={AI_POLICY} />;
}
