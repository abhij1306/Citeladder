import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { domAnimation, LazyMotion } from 'motion/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { Button } from './button';
import { Checkbox } from './checkbox';
import { Disclosure } from './disclosure';
import { RadioGroup } from './radio-group';
import { SearchField } from './search-field';
import { Select } from './select';
import { TabPanel, Tabs } from './tabs';

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

describe('authenticated interaction primitives', () => {
  it('makes a pending Button busy and prevents another submission', () => {
    render(
      <Button pending pendingLabel="Saving…">
        Save
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Saving…' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
  });

  it('clears a controlled SearchField without replacing its owner', async () => {
    const user = userEvent.setup();
    function Harness() {
      const [value, setValue] = useState('orphan');
      return <SearchField value={value} onValueChange={setValue} aria-label="Find issues" />;
    }
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Clear search' }));
    expect(screen.getByRole('searchbox', { name: 'Find issues' })).toHaveValue('');
  });

  it('prevents the clear control from changing a disabled SearchField', async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <SearchField
        disabled
        value="orphan"
        onValueChange={onValueChange}
        aria-label="Find issues"
      />,
    );

    const clear = screen.getByRole('button', { name: 'Clear search' });
    expect(clear).toBeDisabled();
    await user.click(clear);
    expect(onValueChange).not.toHaveBeenCalled();
  });

  it('opens Select options and commits a controlled value', async () => {
    const user = userEvent.setup();
    function Harness() {
      const [value, setValue] = useState<'all' | 'high'>('all');
      return (
        <Select
          value={value}
          onValueChange={setValue}
          ariaLabel="Severity"
          options={[
            { value: 'all', label: 'All' },
            { value: 'high', label: 'High' },
          ]}
        />
      );
    }
    render(<Harness />);
    await user.click(screen.getByRole('combobox', { name: 'Severity' }));
    await user.click(screen.getByRole('option', { name: 'High' }));
    expect(screen.getByRole('combobox', { name: 'Severity' })).toHaveTextContent('High');
  });

  it('uses Radix keyboard selection and panel wiring for Tabs', async () => {
    const user = userEvent.setup();
    function Harness() {
      const [value, setValue] = useState<'one' | 'two'>('one');
      return (
        <LazyMotion features={domAnimation} strict>
          <Tabs
            value={value}
            onValueChange={setValue}
            ariaLabel="Views"
            items={[
              { value: 'one', label: 'One' },
              { value: 'two', label: 'Two' },
            ]}
          >
            <TabPanel value="one">First panel</TabPanel>
            <TabPanel value="two">Second panel</TabPanel>
          </Tabs>
        </LazyMotion>
      );
    }
    render(<Harness />);
    screen.getByRole('tab', { name: 'One' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Two' })).toHaveAttribute('data-state', 'active');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Second panel');
  });

  it('expands Disclosure and exposes checkbox/radio state', async () => {
    const user = userEvent.setup();
    const onCheck = vi.fn();
    const onRadio = vi.fn();
    render(
      <>
        <Disclosure title="Evidence">Persisted source</Disclosure>
        <Checkbox checked={false} onCheckedChange={onCheck} label="Include archived" />
        <RadioGroup
          value="a"
          onValueChange={onRadio}
          ariaLabel="Mode"
          options={[
            { value: 'a', label: 'A' },
            { value: 'b', label: 'B' },
          ]}
        />
      </>,
    );
    await user.click(screen.getByRole('button', { name: 'Evidence' }));
    expect(screen.getByText('Persisted source')).toBeVisible();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include archived' }));
    fireEvent.click(screen.getByRole('radio', { name: 'B' }));
    expect(onCheck).toHaveBeenCalledWith(true);
    expect(onRadio).toHaveBeenCalledWith('b');
  });
});
