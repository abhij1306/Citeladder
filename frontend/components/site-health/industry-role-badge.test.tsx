import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { IndustryRoleBadge, abstentionLabel, industryRoleLabel } from './industry-role-badge';

describe('industryRoleLabel', () => {
  it('keeps the fully-qualified pack role id', () => {
    // The namespace is meaningful: education.fees and commerce.fees are
    // different roles and must not collapse to the same display text.
    expect(industryRoleLabel('education.admissions_overview')).toBe(
      'education.admissions_overview',
    );
    expect(industryRoleLabel('commerce.fees')).not.toBe(industryRoleLabel('education.fees'));
  });

  it('never title-cases an unreviewed id into a fake label', () => {
    expect(industryRoleLabel('newpack.some_new_role')).toBe('newpack.some_new_role');
  });
});

describe('IndustryRoleBadge', () => {
  it('shows the role when one was selected', () => {
    render(<IndustryRoleBadge roleId="education.fees" />);
    expect(screen.getByText('education.fees')).toBeInTheDocument();
  });

  it('distinguishes an executed abstention from missing data', () => {
    // Ran and declined -> "Unclassified" with the specific reason.
    const { unmount } = render(<IndustryRoleBadge roleId={null} abstentionReason="schema_only" />);
    expect(screen.getByText('Unclassified')).toBeInTheDocument();
    expect(screen.getByTitle(abstentionLabel('schema_only'))).toBeInTheDocument();
    unmount();

    // Never ran -> placeholder, NOT "Unclassified".
    render(<IndustryRoleBadge roleId={null} />);
    expect(screen.queryByText('Unclassified')).not.toBeInTheDocument();
  });
});
