import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import Page from './page';

const originalBooking = process.env.DEMO_BOOKING_URL;
const originalEmail = process.env.PUBLIC_SALES_EMAIL;

afterEach(() => {
  if (originalBooking === undefined) delete process.env.DEMO_BOOKING_URL;
  else process.env.DEMO_BOOKING_URL = originalBooking;
  if (originalEmail === undefined) delete process.env.PUBLIC_SALES_EMAIL;
  else process.env.PUBLIC_SALES_EMAIL = originalEmail;
});

describe('Demo page', () => {
  it('uses the approved HTTPS booking destination', () => {
    process.env.DEMO_BOOKING_URL = 'https://cal.example.com/citeladder';
    process.env.PUBLIC_SALES_EMAIL = 'sales@example.com';
    render(<Page />);
    expect(screen.getByRole('link', { name: /schedule demo/i })).toHaveAttribute(
      'href',
      'https://cal.example.com/citeladder',
    );
  });

  it('falls back honestly to public sales email', () => {
    delete process.env.DEMO_BOOKING_URL;
    process.env.PUBLIC_SALES_EMAIL = 'sales@example.com';
    render(<Page />);
    expect(screen.getByRole('link', { name: /email sales/i })).toHaveAttribute(
      'href',
      'mailto:sales@example.com',
    );
  });

  it('converts to self-serve when no booking channel is configured', () => {
    delete process.env.DEMO_BOOKING_URL;
    delete process.env.PUBLIC_SALES_EMAIL;
    render(<Page />);
    expect(screen.queryByRole('link', { name: /schedule demo|email sales/i })).toBeNull();
    // "Start free" promised a tier that does not exist in this release.
    expect(screen.queryByRole('link', { name: /start free/i })).toBeNull();
    expect(screen.getAllByRole('link', { name: /compare plans/i })[0]).toHaveAttribute(
      'href',
      '/pricing',
    );
    expect(screen.getByText(/self-serve signup is open now/i)).toBeInTheDocument();
  });
});
