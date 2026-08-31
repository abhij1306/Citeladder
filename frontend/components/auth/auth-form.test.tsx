import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { AuthPasswordField } from './auth-form';

describe('AuthPasswordField', () => {
  it('keeps the visibility control focused while changing the native input type', async () => {
    const user = userEvent.setup();
    render(
      <AuthPasswordField
        label="Password"
        inputProps={{ name: 'password' }}
        autoComplete="current-password"
        placeholder="Enter password"
      />,
    );

    const input = screen.getByPlaceholderText('Enter password');
    const toggle = screen.getByRole('button', { name: 'Show Password' });
    expect(input).toHaveAttribute('type', 'password');
    await user.click(toggle);
    expect(input).toHaveAttribute('type', 'text');
    expect(screen.getByRole('button', { name: 'Hide Password' })).toHaveFocus();
  });
});
