'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { ContentScreen } from '@/components/content/content-screen';

function ContentSurface() {
  const searchParams = useSearchParams();
  return <ContentScreen opportunityId={searchParams.get('opportunity_id')} />;
}

export default function ContentPage() {
  return (
    <Suspense fallback={null}>
      <ContentSurface />
    </Suspense>
  );
}
