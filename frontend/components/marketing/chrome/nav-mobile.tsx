import { ChevronDown } from 'lucide-react';
import Link from 'next/link';
import { Fragment } from 'react';

import { NAV_DROPS, NAV_LINKS, type NavDropKey } from '@/lib/marketing-content/nav';
import { cn } from '@/lib/utils';

import { NavItemLink } from './nav-items';

type MobileNavigationProps = {
  isAuthenticated: boolean;
  dashboardHref: string;
  openAcc: NavDropKey | null;
  setOpenAcc: (
    key: NavDropKey | null | ((current: NavDropKey | null) => NavDropKey | null),
  ) => void;
  closeMenu: () => void;
};

/** Mobile accordion navigation, rendered only while the menu is open. */
export function MobileNavigation({
  isAuthenticated,
  dashboardHref,
  openAcc,
  setOpenAcc,
  closeMenu,
}: Readonly<MobileNavigationProps>) {
  return (
    <div
      id="mobile-menu"
      className="border-border-subtle bg-background-alt safe-bottom max-h-[calc(100dvh-4rem)] overflow-y-auto overscroll-contain border-t px-6 py-5 lg:hidden"
    >
      {NAV_DROPS.map(({ key, label, href, groups }) => (
        <div key={key} className="border-border-subtle border-b last:border-b-0">
          <div className="flex items-center">
            <Link
              href={href}
              className="website-nav text-foreground flex-1 py-5"
              onClick={closeMenu}
            >
              {label}
            </Link>
            <button
              type="button"
              className="text-foreground grid size-10 place-items-center"
              aria-label={`Open ${label} menu`}
              aria-expanded={openAcc === key}
              aria-controls={`acc-${key}`}
              onClick={() => setOpenAcc((current) => (current === key ? null : key))}
            >
              <ChevronDown
                aria-hidden
                className={cn(
                  'size-4 transition-transform duration-300',
                  openAcc === key && 'rotate-180',
                )}
              />
            </button>
          </div>
          <div id={`acc-${key}`} hidden={openAcc !== key} className="pb-3">
            {groups.map((group) => (
              <Fragment key={group.label ?? 'items'}>
                {group.label && (
                  <p className="website-eyebrow text-muted px-4 pt-4 pb-2">{group.label}</p>
                )}
                {group.items.map((item) => (
                  <NavItemLink key={item.title} item={item} onSelect={closeMenu} />
                ))}
              </Fragment>
            ))}
          </div>
        </div>
      ))}

      <div className="mt-5 grid gap-3">
        {NAV_LINKS.map(({ label, href }) => (
          <Link
            key={href}
            href={href}
            className="website-nav text-foreground py-3"
            onClick={closeMenu}
          >
            {label}
          </Link>
        ))}
        <Link
          href={isAuthenticated ? dashboardHref : '/login'}
          className="website-nav text-muted py-3"
          onClick={closeMenu}
        >
          {isAuthenticated ? 'Dashboard' : 'Log in'}
        </Link>
      </div>
    </div>
  );
}
