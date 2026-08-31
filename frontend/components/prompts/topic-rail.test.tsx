import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ComponentProps } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';
import type { Topic } from '@/lib/api/types';

import { TopicRail } from './topic-rail';

function makeTopic(overrides: Partial<Topic> = {}): Topic {
  return {
    id: '55555555-5555-4555-8555-555555555555',
    project_id: '11111111-1111-4111-8111-111111111111',
    name: 'Footwear',
    description: '',
    origin: 'manual',
    active_count: 0,
    proposed_count: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  } as Topic;
}

function renderRail(props: Partial<ComponentProps<typeof TopicRail>> = {}) {
  return render(
    <TooltipProvider>
      <TopicRail
        topics={[makeTopic()]}
        selectedTopicId={null}
        onSelect={() => {}}
        onCreate={() => {}}
        onDelete={() => {}}
        {...props}
      />
    </TooltipProvider>,
  );
}

describe('TopicRail layout containment', () => {
  it('renders as a contained raised panel without clipping its action edge', () => {
    renderRail();

    const rail = screen.getByRole('navigation', { name: 'Topics' });
    // Long labels truncate within their row; the panel itself does not clip
    // the reserved delete-action slot or its focus treatment.
    expect(rail).not.toHaveClass('overflow-hidden');
    expect(rail).toHaveClass('min-w-0');
    expect(rail).not.toHaveClass('border');
    expect(rail).toHaveClass('shadow-card');
    expect(rail).toHaveClass('bg-panel');
    // Desktop: sticky so the rail stays put while the right pane scrolls.
    expect(rail).toHaveClass('lg:sticky');
    // The full rail is desktop-only; the narrow selector is hidden at lg+.
    expect(rail).toHaveClass('hidden');
    expect(rail).toHaveClass('lg:grid');
  });

  it('truncates long topic names inside the rail without expanding it', () => {
    const longName = 'Best storage solutions for very small studio apartments in dense cities';
    renderRail({ topics: [makeTopic({ name: longName })] });

    // Scope to the rail nav — the narrow <select> also renders the name.
    const rail = screen.getByRole('navigation', { name: 'Topics' });
    const label = within(rail).getByText(longName);
    expect(label).toHaveClass('truncate');
    expect(label).toHaveClass('min-w-0');
    const deleteAction = within(rail).getByRole('button', { name: `Delete topic ${longName}` });
    expect(deleteAction).toHaveClass('size-8');
    expect(deleteAction).not.toHaveClass('opacity-0');
  });

  it('preserves topic selection and create/delete actions', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onCreate = vi.fn();
    const onDelete = vi.fn();
    const topic = makeTopic({ active_count: 3, proposed_count: 2 });

    const rail = renderRail({ topics: [topic], onSelect, onCreate, onDelete });
    const nav = within(screen.getByRole('navigation', { name: 'Topics' }));

    await user.click(nav.getByRole('button', { name: /^Footwear/ }));
    expect(onSelect).toHaveBeenCalledWith(topic.id);

    await user.click(nav.getByRole('button', { name: 'Add topic' }));
    await user.type(nav.getByRole('textbox', { name: 'Topic name' }), 'Apparel');
    await user.click(nav.getByRole('button', { name: 'Add' }));
    expect(onCreate).toHaveBeenCalledWith('Apparel');

    await user.click(nav.getByRole('button', { name: 'Delete topic Footwear' }));
    expect(onDelete).toHaveBeenCalledWith(topic);

    rail.unmount();
  });

  it('marks the selected topic with aria-current', () => {
    const topic = makeTopic();
    renderRail({ topics: [topic], selectedTopicId: topic.id });

    const nav = within(screen.getByRole('navigation', { name: 'Topics' }));
    const selected = nav.getByRole('button', { name: /^Footwear/ });
    expect(selected).toHaveAttribute('aria-current', 'true');
  });
});

describe('TopicRail narrow selector', () => {
  it('renders a full-width Topics select for narrow viewports that filters by topic', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const topic = makeTopic({ name: 'Footwear' });

    renderRail({ topics: [topic], onSelect });

    // The narrow variant is the shared labelled Select, not part of the rail nav.
    const select = screen.getByRole('combobox', { name: 'Topics' });
    expect(select).toHaveTextContent('All topics');
    await user.click(select);
    expect(screen.getByRole('option', { name: 'All topics' })).toBeInTheDocument();
    await user.click(screen.getByRole('option', { name: 'Footwear' }));
    expect(onSelect).toHaveBeenCalledWith(topic.id);
  });

  it('maps the "All topics" option back to a null selection', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const topic = makeTopic();

    renderRail({ topics: [topic], selectedTopicId: topic.id, onSelect });

    const select = screen.getByRole('combobox', { name: 'Topics' });
    expect(select).toHaveTextContent('Footwear');
    await user.click(select);
    await user.click(screen.getByRole('option', { name: 'All topics' }));
    expect(onSelect).toHaveBeenCalledWith(null);
  });
});

describe('TopicRail error handling', () => {
  it('surfaces a load failure in both the rail and the narrow selector', () => {
    renderRail({ loadError: true });
    const alerts = screen.getAllByRole('alert');
    expect(alerts).toHaveLength(2);
    for (const alert of alerts) {
      expect(alert).toHaveTextContent("Couldn't load topics");
    }
    // One alert per responsive variant: inside the desktop rail <nav>, and
    // beside the narrow <select> (outside the nav).
    const rail = screen.getByRole('navigation', { name: 'Topics' });
    const [inRail, outsideRail] = [
      alerts.filter((a) => rail.contains(a)),
      alerts.filter((a) => !rail.contains(a)),
    ];
    expect(inRail).toHaveLength(1);
    expect(outsideRail).toHaveLength(1);
  });

  it('renders a create/delete action error', () => {
    renderRail({ actionError: 'Topic name already exists' });
    expect(screen.getAllByText('Topic name already exists').length).toBeGreaterThan(0);
  });

  it('keeps the add form open with the typed name when create fails', async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn().mockRejectedValue(new Error('boom'));

    renderRail({ onCreate });
    const nav = within(screen.getByRole('navigation', { name: 'Topics' }));

    await user.click(nav.getByRole('button', { name: 'Add topic' }));
    const field = nav.getByRole('textbox', { name: 'Topic name' });
    await user.type(field, 'Apparel');
    await user.click(nav.getByRole('button', { name: 'Add' }));

    expect(onCreate).toHaveBeenCalledWith('Apparel');
    // Form stays open with the value intact so the user can retry.
    expect(nav.getByRole('textbox', { name: 'Topic name' })).toHaveValue('Apparel');
  });

  it('clears the add form after a successful create', async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn().mockResolvedValue(undefined);

    renderRail({ onCreate });
    const nav = within(screen.getByRole('navigation', { name: 'Topics' }));

    await user.click(nav.getByRole('button', { name: 'Add topic' }));
    await user.type(nav.getByRole('textbox', { name: 'Topic name' }), 'Apparel');
    await user.click(nav.getByRole('button', { name: 'Add' }));

    expect(onCreate).toHaveBeenCalledWith('Apparel');
    // Form collapses on success.
    expect(nav.queryByRole('textbox', { name: 'Topic name' })).not.toBeInTheDocument();
  });
});
