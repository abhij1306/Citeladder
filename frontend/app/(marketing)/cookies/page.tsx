import type { Metadata } from 'next';

import { LegalDocumentView } from '@/components/marketing/pages/legal';
import { COOKIE_POLICY } from '@/lib/marketing-content/legal';

export const metadata: Metadata = {
  title: 'Cookie Policy',
  description: COOKIE_POLICY.description,
  alternates: { canonical: '/cookies' },
};

export default function CookiesPage() {
  return <LegalDocumentView document={COOKIE_POLICY} />;
}
