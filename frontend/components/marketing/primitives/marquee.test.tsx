import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Marquee } from './marquee';

function renderStrip(props: Partial<Parameters<typeof Marquee>[0]> = {}) {
  return render(
    <Marquee label="Test strip" {...props}>
      <span>alpha</span>
      <span>beta</span>
    </Marquee>,
  );
}

describe('Marquee', () => {
  it('repeats the list enough times to overflow and loop seamlessly', () => {
    const { container } = renderStrip();
    // Four copies of a two-item list by default.
    expect(container.querySelectorAll('span')).toHaveLength(8);
    expect(container.querySelectorAll('.citeladder-marquee-track > div')).toHaveLength(4);
  });

  it('travels exactly one copy per cycle, whatever the copy count', () => {
    const { container } = renderStrip({ copies: 5 });
    const track = container.querySelector('.citeladder-marquee-track');
    // 1/5 of the track is one copy — translating a fixed -50% would tear the
    // seam as soon as the copy count changed.
    expect(track).toHaveStyle({ '--citeladder-marquee-copy': '20%' });
  });

  it('exposes the items only once to assistive tech', () => {
    const { container } = renderStrip();
    // Every copy after the first is aria-hidden, so the list is announced
    // once. Asserted structurally: getAllByText walks the DOM rather than the
    // accessibility tree, so it would count all copies and prove nothing.
    expect(container.querySelectorAll('[aria-hidden="true"] span')).toHaveLength(6);
    expect(container.querySelectorAll(':not([aria-hidden="true"]) > span')).toHaveLength(2);
  });

  it('names the strip as a whole', () => {
    renderStrip({ label: 'Answer engines' });
    expect(screen.getByRole('group', { name: 'Answer engines' })).toBeInTheDocument();
  });

  it('scrolls leftward by default and marks the reverse direction explicitly', () => {
    const { container: left } = renderStrip();
    expect(left.querySelector('.citeladder-marquee-track')).not.toHaveAttribute('data-direction');

    const { container: right } = renderStrip({ direction: 'right' });
    expect(right.querySelector('.citeladder-marquee-track')).toHaveAttribute(
      'data-direction',
      'reverse',
    );
  });

  it('drives cycle length from the speed prop', () => {
    const { container } = renderStrip({ speed: 25 });
    const track = container.querySelector('.citeladder-marquee-track');
    expect(track).toHaveStyle({ '--citeladder-marquee-duration': '25s' });
  });
});
