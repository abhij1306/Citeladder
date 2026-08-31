'use client';

import { useMutation } from '@tanstack/react-query';
import { LogOut, Map } from 'lucide-react';
import Link from 'next/link';

import {
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownLabel,
  DropdownSeparator,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import { authApi } from '@/lib/api/auth';
import { useSession } from '@/lib/auth/session-guard';
import { ICONS } from '@/lib/icons';
import { cn, emailInitials } from '@/lib/utils';

/**
 * UserMenu (F5) — shows the current user (from F4's `useSession`) and a logout
 * action. Logout clears account-scoped client state only after the backend has
 * confirmed cookie revocation. A failed request keeps the authenticated UI and
 * offers a retry instead of pretending the session ended.
 */
const SettingsIcon = ICONS.settings;

export function UserMenu({ className }: Readonly<{ className?: string }>) {
  const { user, clearSession } = useSession();

  // clearSession removes account-scoped cache only after cookie revocation succeeds.
  // react-doctor-disable-next-line
  const logout = useMutation({
    mutationFn: () => authApi.logout(),
    onSuccess: () => clearSession(),
  });

  return (
    <div className={cn('flex items-center gap-1', className)}>
      <Dropdown>
        <DropdownTrigger className="focus-ring hover:bg-background-alt flex min-w-0 flex-1 items-center gap-2 rounded-sm px-2 py-1 text-left transition-colors">
          <span
            aria-hidden
            className="bg-background-alt text-secondary flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-medium uppercase"
          >
            {emailInitials(user.email)}
          </span>
          <span className="text-secondary min-w-0 flex-1 truncate text-sm">{user.email}</span>
        </DropdownTrigger>
        <DropdownContent align="start" side="top" className="w-56">
          <DropdownLabel>{user.email}</DropdownLabel>
          <DropdownSeparator className="bg-border-subtle my-1 h-px" />
          <DropdownItem asChild>
            <Link href="/settings">
              <SettingsIcon className="size-4 shrink-0" aria-hidden />
              <span>Settings</span>
            </Link>
          </DropdownItem>
          <DropdownItem
            onSelect={() => {
              window.dispatchEvent(new Event('citeladder:replay-product-tour'));
            }}
          >
            <Map className="size-4 shrink-0" aria-hidden />
            <span>Replay product tour</span>
          </DropdownItem>
          <DropdownItem
            onSelect={(event) => {
              event.preventDefault();
              logout.mutate();
            }}
            disabled={logout.isPending}
          >
            <LogOut className="size-4 shrink-0" aria-hidden />
            <span>{logout.isPending ? 'Signing out…' : 'Sign out'}</span>
          </DropdownItem>
          {logout.isError ? (
            <p role="alert" className="text-danger px-2 py-1.5 text-xs">
              Sign out failed. Your session is still active; please try again.
            </p>
          ) : null}
        </DropdownContent>
      </Dropdown>
    </div>
  );
}
