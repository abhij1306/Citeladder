import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AI_POLICY, PRIVACY_POLICY, TERMS_OF_SERVICE } from '@/lib/marketing-content/legal';

import PrivacyPage from './page';

describe('Privacy page', () => {
  it('renders the policy title and section headings', () => {
    render(<PrivacyPage />);

    expect(
      screen.getByRole('heading', { level: 1, name: PRIVACY_POLICY.title }),
    ).toBeInTheDocument();
    for (const section of PRIVACY_POLICY.sections) {
      expect(screen.getByRole('heading', { level: 2, name: section.title })).toBeInTheDocument();
    }
    const toc = screen.getByRole('navigation', { name: 'On this page' });
    expect(within(toc).getAllByRole('link')).toHaveLength(PRIVACY_POLICY.sections.length);
  });

  it('links to the sibling legal documents', () => {
    render(<PrivacyPage />);

    const other = screen.getByRole('navigation', { name: 'Other legal documents' });
    expect(within(other).getByRole('link', { name: TERMS_OF_SERVICE.title })).toHaveAttribute(
      'href',
      '/terms',
    );
    expect(within(other).getByRole('link', { name: 'Cookies' })).toHaveAttribute(
      'href',
      '/cookies',
    );
    expect(within(other).getByRole('link', { name: AI_POLICY.title })).toHaveAttribute(
      'href',
      '/ai-policy',
    );
  });
});
