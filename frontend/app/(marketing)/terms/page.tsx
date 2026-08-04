import type { Metadata } from 'next';

import { LegalDocumentView } from '@/components/marketing/pages/legal';
import { TERMS_OF_SERVICE } from '@/lib/marketing-content/legal';

export const metadata: Metadata = {
  title: 'Terms of Service',
  description: TERMS_OF_SERVICE.description,
  alternates: { canonical: '/terms' },
};

export default function TermsPage() {
  return <LegalDocumentView document={TERMS_OF_SERVICE} />;
}
