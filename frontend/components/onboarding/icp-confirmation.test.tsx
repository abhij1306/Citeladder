import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { IcpConfirmation, hasConfirmedIcp } from '@/components/onboarding/icp-confirmation';
import type { DiscoveryProfile } from '@/lib/api/brand-discoveries';

function profile(overrides: Partial<DiscoveryProfile> = {}): DiscoveryProfile {
  return {
    description: 'A commerce platform',
    positioning: 'Reliable product data',
    products_services: ['Product feeds'],
    target_audience: 'Retailers',
    industry: 'Commerce software',
    business_type: 'b2b',
    price_tier: 'premium',
    field_confidence: {},
    category: 'product feed management platform',
    category_options: [],
    category_aliases: ['feed management software'],
    category_terms: ['product feed management', 'marketplace integrations'],
    jobs_to_be_done: ['sell on marketplaces'],
    sector: 'Software',
    business_model: 'b2b_saas',
    secondary_business_models: [],
    market_scope: 'global',
    buyer_register: 'research_comparative',
    buyer_roles: [],
    service_areas: [],
    knowledge_strength: 'strong',
    ...overrides,
  };
}

describe('hasConfirmedIcp', () => {
  it('gates only on what the screen actually shows', () => {
    // Positioning and audience are no longer asked for here, so they must not
    // block a user on a field they were never presented with.
    expect(hasConfirmedIcp(profile())).toBe(true);
    expect(hasConfirmedIcp(profile({ positioning: '', target_audience: '' }))).toBe(true);
    expect(hasConfirmedIcp(profile({ category: '   ' }))).toBe(false);
    expect(hasConfirmedIcp(null)).toBe(false);
  });
});

describe('IcpConfirmation', () => {
  it('asks three questions, all answerable by clicking', () => {
    render(<IcpConfirmation profile={profile()} onChange={vi.fn()} />);

    const what = screen.getByRole('heading', { name: 'What you sell' });
    const who = screen.getByRole('heading', { name: 'Who buys it' });
    const where = screen.getByRole('heading', { name: 'Where they buy it' });
    expect(what).toHaveClass('flow-group-title');
    expect(who).toHaveClass('flow-group-title');
    expect(where).toHaveClass('flow-group-title');
    expect(who.closest('section')?.parentElement).toBe(where.closest('section')?.parentElement);
    expect(who.closest('section')?.parentElement).toHaveClass('flow-pair');
    expect(where.closest('section')).toHaveClass('flow-group');
    expect(screen.queryByLabelText(/positioning/i)).toBeNull();
    expect(screen.queryByLabelText(/description/i)).toBeNull();
  });

  it('caps the category choices so the screen stays short', () => {
    render(
      <IcpConfirmation
        profile={profile({
          category_options: ['one', 'two', 'three', 'four'],
          category_aliases: ['five'],
        })}
        onChange={vi.fn()}
      />,
    );

    // Three suggestions plus the explicit escape hatch. Matched by exact name:
    // a loose regex counted the escape chip too, because "None of these"
    // contains "one".
    for (const name of ['product feed management platform', 'one', 'two']) {
      expect(screen.getByRole('radio', { name })).toBeVisible();
    }
    expect(screen.queryByRole('radio', { name: 'three' })).toBeNull();
    expect(screen.getByRole('radio', { name: 'None of these' })).toBeVisible();
  });

  it('names the escape hatch for what it is when there is nothing to reject', () => {
    // With no suggestions on screen, "None of these" refers to an empty set.
    render(
      <IcpConfirmation
        profile={profile({ category: '', category_aliases: [] })}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole('radio', { name: 'Other' })).toBeVisible();
  });

  it('offers one regional choice and keeps every choice on screen after selection', async () => {
    // Regression: selecting a scope made the rest of the options vanish.
    const onChange = vi.fn();
    const { rerender } = render(<IcpConfirmation profile={profile()} onChange={onChange} />);

    expect(screen.queryByRole('radio', { name: 'City by city' })).toBeNull();
    expect(screen.queryByRole('radio', { name: 'Across a region' })).toBeNull();
    await userEvent.click(screen.getByRole('radio', { name: 'Regional' }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ market_scope: 'regional' }));
    rerender(<IcpConfirmation profile={profile({ market_scope: 'local' })} onChange={onChange} />);

    expect(screen.getByRole('radio', { name: 'Regional' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Worldwide' })).toBeVisible();
    expect(screen.getByRole('radio', { name: 'Businesses' })).toBeVisible();
    expect(screen.getByText('What you sell')).toBeVisible();
  });

  it('reveals a text field only when the suggestions are rejected', async () => {
    render(<IcpConfirmation profile={profile()} onChange={vi.fn()} />);

    expect(screen.queryByLabelText(/describe what you sell/i)).toBeNull();
    await userEvent.click(screen.getByRole('radio', { name: 'None of these' }));
    expect(screen.getByLabelText(/describe what you sell/i)).toBeVisible();
  });

  it('drops the rejected suggestion so it cannot be submitted silently', async () => {
    // Regression: "None of these" only flipped the input on. The rejected
    // category stayed in the payload, the field looked empty, and Create
    // project stayed enabled — so the user shipped the label they rejected.
    const onChange = vi.fn();
    const { rerender } = render(<IcpConfirmation profile={profile()} onChange={onChange} />);
    expect(hasConfirmedIcp(profile())).toBe(true);

    await userEvent.click(screen.getByRole('radio', { name: 'None of these' }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ category: '' }));
    const rejected = profile({ category: '' });
    rerender(<IcpConfirmation profile={rejected} onChange={onChange} />);
    expect(hasConfirmedIcp(rejected)).toBe(false);

    const field = screen.getByLabelText(/describe what you sell/i);
    expect(field).toHaveValue('');
    await userEvent.type(field, 'x');
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ category: 'x' }));
    expect(hasConfirmedIcp(profile({ category: 'x' }))).toBe(true);
  });

  it('says what the category controls, because everything downstream uses it', () => {
    // A wrong category produces wrong competitors and wrong prompts. The user
    // has to know that before skimming past it.
    render(<IcpConfirmation profile={profile()} onChange={vi.fn()} />);

    expect(
      screen.getByText(/competitors and tracked questions are built from this/i),
    ).toBeVisible();
  });

  it('switches category with one click', async () => {
    const onChange = vi.fn();
    render(
      <IcpConfirmation
        profile={profile({ category_options: ['marketplace syndication software'] })}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByRole('radio', { name: /marketplace syndication software/i }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ category: 'marketplace syndication software' }),
    );
  });
});
