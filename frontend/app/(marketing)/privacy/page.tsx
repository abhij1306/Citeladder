import type { Metadata } from 'next';

import { LegalDocumentView } from '@/components/marketing/pages/legal';
import { PRIVACY_POLICY } from '@/lib/marketing-content/legal';

export const metadata: Metadata = {
  title: 'Privacy Policy',
  description: PRIVACY_POLICY.description,
  alternates: { canonical: '/privacy' },
};

export default function PrivacyPage() {
  return <LegalDocumentView document={PRIVACY_POLICY} />;
}
