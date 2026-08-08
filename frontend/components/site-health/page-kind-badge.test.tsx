import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { PageKindBadge } from './page-kind-badge';

describe('PageKindBadge', () => {
  it('renders the humanized page-kind label as a badge', () => {
    render(<PageKindBadge pageKind="about_contact" />);
    expect(screen.getByText('About / Contact')).toBeInTheDocument();
  });

  it('renders the acronym label untouched (FAQ, not Faq)', () => {
    render(<PageKindBadge pageKind="faq" />);
    expect(screen.getByText('FAQ')).toBeInTheDocument();
  });

  it('renders the — placeholder for an unclassified page (null) — never a guessed type', () => {
    render(<PageKindBadge pageKind={null} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('renders the — placeholder when the projection does not carry the field', () => {
    render(<PageKindBadge pageKind={undefined} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
