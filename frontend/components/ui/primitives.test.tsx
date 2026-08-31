import { render, screen, within } from '@testing-library/react';
import { createRef } from 'react';
import { describe, expect, it } from 'vitest';

import { Alert } from './alert';
import { Badge } from './badge';
import { Button } from './button';
import { buttonVariants } from './button-variants';
import { Card, CardContent, CardEyebrow, CardHeader, CardTitle } from './card';
import { Field } from './field';
import { Input } from './input';
import { ScoreBar } from './score-bar';
import { ScoreRing } from './score-ring';
import { Skeleton } from './skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRecordMetricCell,
  TableRow,
} from './table';
import { TrendChart } from './trend-chart';
import { UnavailableValue } from './unavailable-value';
import { scoreBand } from './score-band';
import { MetricGroup, MetricItem, WorkspacePane } from './workspace';

describe('Button', () => {
  it('renders default variant/size classes', () => {
    render(<Button>Save</Button>);
    const btn = screen.getByRole('button', { name: 'Save' });
    // Primary variant → navy action fill with its verified foreground and the
    // semantic app control radius; the pill is retired for buttons.
    expect(btn.className).toContain('bg-action');
    expect(btn.className).toContain('text-action-fg');
    expect(btn.className).toContain('rounded-[var(--radius-control)]');
    expect(btn.className).not.toContain('rounded-full');
    expect(btn.className).toContain('h-[var(--control-height)]');
    // real <button> defaults to type=button (no accidental submit)
    expect(btn).toHaveAttribute('type', 'button');
  });

  it('applies the requested variant and size', () => {
    render(
      <Button variant="destructive" size="lg">
        Delete
      </Button>,
    );
    const btn = screen.getByRole('button', { name: 'Delete' });
    expect(btn.className).toContain('bg-danger-solid');
    // White label on the deepened fill — not the dark ink the flat phase used.
    expect(btn.className).toContain('text-danger-fg');
    // Hover walks the ramp (like primary) rather than fading opacity, which
    // used to wash the label out along with the fill.
    expect(btn.className).toContain('hover:bg-danger-solid-hover');
    expect(btn.className).toContain('h-[var(--control-height-lg)]');
  });

  it('renders as the child element when asChild is set (Radix Slot)', () => {
    render(
      <Button asChild variant="secondary">
        {/* oxlint-disable-next-line nextjs/no-html-link-for-pages -- not
            navigation: this asserts Radix Slot forwards the button surface onto
            whatever child it is given, and oxlint's port of the rule has no
            route table to check `/next` against as the ESLint version did. */}
        <a href="/next">Go</a>
      </Button>,
    );
    const link = screen.getByRole('link', { name: 'Go' });
    expect(link.tagName).toBe('A');
    expect(link).toHaveAttribute('href', '/next');
    // The button surface classes are forwarded onto the anchor.
    expect(link.className).toContain('bg-well');
    // asChild must NOT inject a type attribute onto the anchor.
    expect(link).not.toHaveAttribute('type');
  });

  it('buttonVariants is a pure class generator', () => {
    expect(buttonVariants({ variant: 'ghost', size: 'sm' })).toContain(
      'h-[var(--control-height-sm)]',
    );
  });

  it('keeps popup triggers stationary while preserving button press feedback elsewhere', () => {
    render(
      <>
        <Button aria-haspopup="menu">Filters</Button>
        <Button>Save</Button>
      </>,
    );
    const trigger = screen.getByRole('button', { name: 'Filters' });
    expect(trigger.className).toContain('active:scale-100');
    expect(trigger.className).not.toContain('active:scale-[0.98]');
    expect(screen.getByRole('button', { name: 'Save' }).className).toContain('active:scale-[0.98]');
  });
});

describe('Badge', () => {
  it('maps status variant to the success token classes', () => {
    render(
      <Badge variant="status" value="success">
        Configured
      </Badge>,
    );
    const badge = screen.getByText('Configured');
    expect(badge.className).toContain('bg-success-bg');
    expect(badge.className).toContain('text-success-text');
    // Flat language: sans rectangles, not mono pills.
    expect(badge.className).toContain('rounded-sm');
    expect(badge.className).not.toContain('font-mono');
  });

  it('keeps the pill shape for run-status badges only', () => {
    const { unmount } = render(
      <Badge variant="run-status" value="running">
        Running
      </Badge>,
    );
    expect(screen.getByText('Running').className).toContain('rounded-full');
    unmount();

    render(
      <Badge variant="status" value="info">
        Info
      </Badge>,
    );
    expect(screen.getByText('Info').className).not.toContain('rounded-full');
  });

  it('maps sentiment variant to sentiment tokens', () => {
    render(
      <Badge variant="sentiment" value="negative">
        Negative
      </Badge>,
    );
    expect(screen.getByText('Negative').className).toContain('bg-sentiment-negative-bg');
  });

  it('maps classification variant to citation tokens', () => {
    render(
      <Badge variant="classification" value="owned">
        Owned
      </Badge>,
    );
    expect(screen.getByText('Owned').className).toContain('bg-citation-owned-bg');
  });

  it('maps run-status variant to run-status tokens', () => {
    render(
      <Badge variant="run-status" value="completed">
        Completed
      </Badge>,
    );
    const badge = screen.getByText('Completed');
    expect(badge.className).toContain('bg-run-completed-bg');
    expect(badge.className).toContain('text-run-completed');
  });

  it('falls back to the neutral token when no variant is given', () => {
    render(<Badge>Draft</Badge>);
    expect(screen.getByText('Draft').className).toContain('bg-neutral-bg');
  });
});

describe('Card', () => {
  it('renders panel surface with header/title/content slots', () => {
    render(
      <Card data-testid="card">
        <CardHeader>
          <CardTitle>Visibility</CardTitle>
        </CardHeader>
        <CardContent>Body</CardContent>
      </Card>,
    );
    expect(screen.getByTestId('card').className).toContain('bg-panel');
    expect(screen.getByTestId('card').className).toContain('rounded-[var(--radius-card)]');
    expect(screen.getByTestId('card').className).not.toContain('shadow-card');
    expect(screen.getByTestId('card').className).not.toContain('border');
    expect(screen.getByText('Visibility').tagName).toBe('H3');
    expect(screen.getByText('Body')).toBeInTheDocument();
  });

  it('CardEyebrow renders the shared micro-label recipe (never a heading)', () => {
    render(<CardEyebrow>Visibility score</CardEyebrow>);
    const eyebrow = screen.getByText('Visibility score');
    expect(eyebrow.tagName).toBe('SPAN');
    // Metadata: 12/16 @500, muted, sentence case, and never the mono face.
    expect(eyebrow.className).toContain('text-xs');
    expect(eyebrow.className).toContain('text-muted');
    expect(eyebrow.className).toContain('font-medium');
    expect(eyebrow.className).not.toContain('uppercase');
    expect(eyebrow.className).not.toContain('tracking-');
    expect(eyebrow.className).not.toContain('font-mono');
  });
});

describe('Workspace structures', () => {
  it('keeps panes open by default and makes semantic object styling explicit', () => {
    const { rerender } = render(<WorkspacePane data-testid="pane">Open</WorkspacePane>);
    const pane = screen.getByTestId('pane');
    expect(pane).not.toHaveClass('bg-panel', 'rounded-[var(--radius-card)]');

    rerender(
      <WorkspacePane data-testid="pane" surface="object">
        Object
      </WorkspacePane>,
    );
    expect(screen.getByTestId('pane')).toHaveClass('bg-panel', 'rounded-[var(--radius-card)]');
  });

  it('resets metric separators and inline padding for responsive rows', () => {
    render(
      <MetricGroup data-testid="metrics">
        <MetricItem label="One" value="1" />
        <MetricItem label="Two" value="2" />
      </MetricGroup>,
    );
    expect(screen.getByTestId('metrics')).toHaveClass('sm:divide-x-0');
    expect(screen.getByText('1').parentElement).toHaveClass('sm:odd:ps-0', 'sm:even:pe-0');
  });
});

describe('UnavailableValue', () => {
  it('renders the explicit semantic state with the shared placeholder treatment', () => {
    render(<UnavailableValue state="not_measured" />);
    const value = screen.getByText('Not measured');
    expect(value).toHaveClass('value-placeholder');
  });
});

describe('Table (dense)', () => {
  it('renders header and rows with dense heights', () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Prompt</TableHead>
            <TableHead numeric>Score</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell>How good is X?</TableCell>
            <TableCell numeric>82</TableCell>
          </TableRow>
        </TableBody>
      </Table>,
    );
    const headers = screen.getAllByRole('columnheader');
    expect(headers).toHaveLength(2);
    // Sticky header at the dense height, sentence-case sans micro-label.
    expect(headers[0].className).toContain('h-[var(--table-header-height)]');
    expect(headers[0].className).toContain('sticky');
    // Table headers share the eyebrow recipe (12/16 @500, no uppercase,
    // no tracking); mono stays for values.
    expect(headers[0].className).toContain('text-xs');
    expect(headers[0].className).toContain('font-medium');
    expect(headers[0].className).toContain('whitespace-nowrap');
    expect(headers[0].className).not.toContain('uppercase');
    expect(headers[0].className).not.toContain('font-mono');
    // Flat grid: header sits on the panel and is left-aligned even when numeric.
    expect(headers[0].className).toContain('bg-panel');
    expect(headers[1].className).toContain('text-left');
    // Numeric columns still get tabular numerals.
    expect(headers[1].className).toContain('tabular-nums');

    const rows = screen.getAllByRole('row');
    // 1 header row + 1 body row.
    expect(rows).toHaveLength(2);
    const bodyRow = rows[1];
    expect(bodyRow.className).toContain('h-[var(--table-row-height)]');
    expect(screen.getByText('82').className).toContain('tabular-nums');
    // Cells carry real vertical padding again (the py-0 regression is gone)
    // and no column-separator hairlines.
    const cell = screen.getByText('How good is X?');
    expect(cell.className).not.toContain('py-0');
    expect(cell.className).not.toContain('border-l');
  });

  it('labels numeric values when a table becomes mobile records', () => {
    render(
      <table>
        <tbody>
          <tr>
            <TableRecordMetricCell label="Coverage">82%</TableRecordMetricCell>
          </tr>
        </tbody>
      </table>,
    );

    const cell = screen.getByRole('cell', { name: '82%' });
    expect(cell).toHaveAttribute('data-label', 'Coverage');
    expect(cell).toHaveClass('grid', 'md:table-cell', 'tabular-nums');
  });
});

describe('Input + Field', () => {
  it('wires label to input via generated id, and surfaces errors', () => {
    render(
      <Field label="Email" error="Required">
        {(fieldProps) => <Input placeholder="you@co" {...fieldProps} />}
      </Field>,
    );
    const input = screen.getByPlaceholderText('you@co');
    // Field associates the label htmlFor with the input id.
    const label = screen.getByText('Email');
    expect(label).toHaveAttribute('for', input.id);
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('alert')).toHaveTextContent('Required');
    expect(input.className).toContain('h-[var(--control-height)]');
    // The Phase 1 regressions stay fixed: the field keeps its visible fill
    // (canvas tint on the white card) and its accent focus border, and the
    // Invalid state has its own semantic danger border.
    expect(input.className).toContain('bg-input');
    expect(input.className).toContain('focus:border-accent');
    expect(input.className).toContain('aria-invalid:border-danger');
  });

  it('keeps the native ref and input class while shared adornments own the frame', () => {
    const ref = createRef<HTMLInputElement>();
    render(
      <Input
        ref={ref}
        aria-label="Search"
        startContent={<span data-testid="start">S</span>}
        endContent={<span data-testid="end">E</span>}
        className="input-hook"
        containerClassName="frame-hook"
      />,
    );
    expect(ref.current).toBe(screen.getByRole('textbox', { name: 'Search' }));
    expect(ref.current).toHaveClass('input-hook');
    expect(ref.current?.parentElement).toHaveClass('frame-hook');
    expect(screen.getByTestId('start')).toBeInTheDocument();
    expect(screen.getByTestId('end')).toBeInTheDocument();
  });
});

describe('Alert', () => {
  it('renders a role=alert region with tone token classes', () => {
    render(<Alert tone="danger">Something failed</Alert>);
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Something failed');
    expect(alert.className).toContain('text-danger-text');
    expect(alert.className).not.toContain('bg-danger-bg');
    expect(alert.className).not.toContain('border');
    expect(alert.className).not.toContain('p-4');
  });
});

describe('Skeleton', () => {
  it('renders the shimmer class and is aria-hidden', () => {
    render(<Skeleton className="h-4 w-20" />);
    const el = document.querySelector('.skeleton');
    expect(el).not.toBeNull();
    expect(el).toHaveAttribute('aria-hidden', 'true');
  });
});

describe('scoreBand mapping', () => {
  it('maps values to the four bands', () => {
    expect(scoreBand(10)).toBe('low');
    expect(scoreBand(30)).toBe('mid');
    expect(scoreBand(60)).toBe('good');
    expect(scoreBand(90)).toBe('high');
  });
});

describe('ScoreRing', () => {
  it('renders an ARIA-labelled ring with the score-band stroke and center value', () => {
    render(<ScoreRing value={82} />);
    const ring = screen.getByRole('img', { name: 'Visibility score: 82%' });
    expect(ring).toBeInTheDocument();
    // High band (>=75) → the score-high RING token on the progress arc. Rings
    // use --score-*-ring, not the solid, so the two can diverge per theme.
    expect(ring.querySelector('.stroke-score-high-ring')).not.toBeNull();
    // Center mono value.
    expect(screen.getByText('82')).toBeInTheDocument();
  });

  it('clamps out-of-range values', () => {
    render(<ScoreRing value={140} label="Overflow" />);
    expect(screen.getByRole('img', { name: 'Overflow' })).toBeInTheDocument();
    expect(screen.getByText('100')).toBeInTheDocument();
  });

  it('renders the display-size numeral with numeralSize="lg"', () => {
    render(<ScoreRing value={82} size={128} numeralSize="lg" />);
    const numeral = screen.getByText('82');
    expect(numeral.className).toContain('text-xl');
    expect(numeral).toHaveAttribute('aria-hidden', 'true');
    // The accessible label still lives on the ring, not the numeral.
    expect(screen.getByRole('img', { name: 'Visibility score: 82%' })).toBeInTheDocument();
  });

  it('defaults to the text-heading-sm numeral', () => {
    render(<ScoreRing value={82} />);
    expect(screen.getByText('82').className).toContain('text-heading-sm');
  });
});

describe('ScoreBar', () => {
  it('renders a token-coloured, clamped accessible meter', () => {
    render(<ScoreBar value={140} label="Readiness score" />);
    const meter = screen.getByRole('meter', { name: 'Readiness score' });
    expect(meter).toHaveAttribute('value', '100');
    expect(meter.nextElementSibling?.querySelector('.bg-score-high-ring')).not.toBeNull();
  });
});

describe('TrendChart (cross-run Visibility trend)', () => {
  it('renders with an ARIA label describing the trend', () => {
    render(
      <TrendChart
        label="Visibility trend"
        data={[
          { label: 'Jun', value: 40 },
          { label: 'Jul', value: 70 },
        ]}
      />,
    );
    const chart = screen.getByRole('img', {
      name: 'Visibility trend: Trend from Jun (40) to Jul (70)',
    });
    expect(chart).toBeInTheDocument();
    // Line stroke uses the accent token.
    expect(chart.querySelector('.stroke-accent')).not.toBeNull();
  });

  it('renders a single point without a misleading slope or area', () => {
    render(<TrendChart label="Visibility trend" data={[{ label: 'Jul', value: 55 }]} />);
    const chart = screen.getByRole('img', {
      name: 'Visibility trend: Single point Jul (55)',
    });
    expect(chart).toBeInTheDocument();
    // No connecting line and no area fill for a single point — just a dot.
    expect(chart.querySelector('.stroke-accent')).toBeNull();
    expect(chart.querySelector('.fill-accent-soft')).toBeNull();
    expect(chart.querySelectorAll('circle.fill-accent')).toHaveLength(1);
  });

  it('renders an empty state with no data points', () => {
    render(<TrendChart label="Visibility trend" data={[]} />);
    expect(
      screen.getByRole('img', { name: 'Visibility trend: No trend data' }),
    ).toBeInTheDocument();
  });

  it('marks a version boundary with an accessible warning marker', () => {
    render(
      <TrendChart
        label="Visibility trend"
        data={[
          { label: 'Jun', value: 40 },
          { label: 'Jul', value: 70, versionChange: { note: 'Scoring rule scoring-v2 applied' } },
        ]}
      />,
    );
    const chart = screen.getByRole('img');
    const marker = chart.querySelector('[data-version-marker]');
    expect(marker).not.toBeNull();
    // The change is announced via a <title>, not conveyed by color alone.
    expect(
      within(chart as unknown as HTMLElement).getByText(/Scoring rule scoring-v2 applied/),
    ).toBeInTheDocument();
    // The dashed marker line uses the warning token (bridged), not raw hex.
    expect(chart.querySelector('.stroke-warning')).not.toBeNull();
  });

  it('renders null values as gaps, announces them, and never draws a zero dot', () => {
    render(
      <TrendChart
        label="Visibility trend"
        data={[
          { label: 'Jun', value: 40 },
          { label: 'Jul', value: 50 },
          { label: 'Aug', value: null },
          { label: 'Sep', value: 60 },
          { label: 'Oct', value: 70 },
        ]}
      />,
    );
    const chart = screen.getByRole('img');
    // Endpoints announce the numeric value; the gap is announced explicitly.
    expect(chart).toHaveAttribute(
      'aria-label',
      'Visibility trend: Trend from Jun (40) to Oct (70) Some points are unavailable and shown as gaps.',
    );
    // The null point produces NO dot: only the four available points have dots.
    expect(chart.querySelectorAll('circle.fill-accent')).toHaveLength(4);
    // The line splits across the gap into two separate multi-point sub-paths.
    expect(chart.querySelectorAll('path.stroke-accent')).toHaveLength(2);
  });

  it('announces an unavailable endpoint value as "unavailable"', () => {
    render(
      <TrendChart
        label="Visibility trend"
        data={[
          { label: 'Jun', value: null },
          { label: 'Jul', value: 55 },
        ]}
      />,
    );
    expect(
      screen.getByRole('img', {
        name: 'Visibility trend: Trend from Jun (unavailable) to Jul (55) Some points are unavailable and shown as gaps.',
      }),
    ).toBeInTheDocument();
  });

  it('renders a single available point among nulls as a lone dot (no slope)', () => {
    render(
      <TrendChart
        label="Visibility trend"
        data={[
          { label: 'Jun', value: null },
          { label: 'Jul', value: 55 },
          { label: 'Aug', value: null },
        ]}
      />,
    );
    const chart = screen.getByRole('img');
    // One dot for the lone available point; no line/area (segment length 1).
    expect(chart.querySelectorAll('circle.fill-accent')).toHaveLength(1);
    expect(chart.querySelector('path.stroke-accent')).toBeNull();
    expect(chart.querySelector('.fill-accent-soft')).toBeNull();
  });

  it('scales count metrics against a custom domainMax instead of clamping to 100', () => {
    const data = [
      { label: 'Jun', value: 250 },
      { label: 'Jul', value: 500 },
    ];
    const { unmount } = render(<TrendChart label="Clicks trend" data={data} domainMax={500} />);
    let chart = screen.getByRole('img', {
      name: 'Clicks trend: Trend from Jun (250) to Jul (500)',
    });
    let dots = chart.querySelectorAll('circle.fill-accent');
    // height 120, padding 8 → innerHeight 104: 250/500 → y=60, 500/500 → y=8.
    expect(dots[0]).toHaveAttribute('cy', '60');
    expect(dots[1]).toHaveAttribute('cy', '8');
    unmount();

    // Default domain (100) is unchanged: the same counts clamp to the top.
    render(<TrendChart label="Clicks trend" data={data} />);
    chart = screen.getByRole('img', {
      name: 'Clicks trend: Trend from Jun (250) to Jul (500)',
    });
    dots = chart.querySelectorAll('circle.fill-accent');
    expect(dots[0]).toHaveAttribute('cy', '8');
    expect(dots[1]).toHaveAttribute('cy', '8');
  });
});
