import { ArrowUpRight } from 'lucide-react';
import Link from 'next/link';

import type { NavDropItem } from '@/lib/marketing-content/nav';
import { cn } from '@/lib/utils';

const ROW =
  'group rounded-md flex items-start gap-4 px-4 py-3 transition-colors duration-150 ' +
  'hover:bg-background focus-visible:bg-background';

function RowBody({ item }: Readonly<{ item: NavDropItem }>) {
  return (
    <>
      {'num' in item && (
        <span className="text-accent-text pt-2 font-mono text-xs tabular-nums">{item.num}</span>
      )}
      <span className="min-w-0">
        <span className="text-foreground block text-sm leading-snug font-semibold">
          {item.title}
        </span>
        {/* One line, always: a menu row that wraps turns the panel into a
            wall of paragraphs and doubles its height. */}
        <span className="text-muted mt-2 block truncate text-sm leading-snug">{item.desc}</span>
      </span>
    </>
  );
}

/**
 * One navigation row, shared by the desktop dropdown and the mobile
 * accordion. The only difference between the two surfaces is the ARIA role:
 * the desktop panel is a `menu`, so its rows are `menuitem`s; the mobile
 * accordion is plain content, where that role would be a lie.
 *
 * External rows open in a new tab and say so with a visible glyph rather
 * than relying on the target alone.
 */
function NavRow({
  item,
  onSelect,
  menuitem,
}: Readonly<{ item: NavDropItem; onSelect: () => void; menuitem: boolean }>) {
  const role = menuitem ? 'menuitem' : undefined;

  if ('external' in item && item.external) {
    return (
      <a
        className={cn(ROW, 'justify-between')}
        href={item.href}
        target="_blank"
        rel="noreferrer"
        role={role}
        onClick={onSelect}
      >
        <RowBody item={item} />
        <ArrowUpRight className="text-muted mt-2 size-4 shrink-0" aria-hidden />
      </a>
    );
  }

  return (
    <Link className={ROW} href={item.href} role={role} onClick={onSelect}>
      <RowBody item={item} />
    </Link>
  );
}

/** Desktop dropdown row (inside a `menu`). */
export function DropItemLink(props: Readonly<{ item: NavDropItem; onSelect: () => void }>) {
  return <NavRow {...props} menuitem />;
}

/** Mobile accordion row — same content, no menu semantics. */
export function MobileItemLink(props: Readonly<{ item: NavDropItem; onSelect: () => void }>) {
  return <NavRow {...props} menuitem={false} />;
}
