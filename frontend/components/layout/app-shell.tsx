'use client';

import type { ReactNode } from 'react';
import { ChartNoAxesCombined, Home, ListChecks, Settings, Sparkles } from 'lucide-react';
import Link from 'next/link';

import { CommandPalette } from '@/components/ui/command-palette';
import { BrandAtmosphere } from '@/components/ui/brand-atmosphere';
import { LogoMark } from '@/components/ui/logo-mark';
import { TooltipProvider } from '@/components/ui/tooltip';

import { PageHeader } from './page-header';
import { ProjectSwitcher } from './project-switcher';
import { SidebarNav } from './sidebar-nav';
import { UserMenu } from './user-menu';

/**
 * AppShell — the authed-area chrome in the ADS shell language.
 *
 * Geometry: a 240px left sidebar (`bg-sidebar`, `--sidebar-width`) stacked as
 * logo row → project switcher → grouped nav → user card, each
 * band separated by a hairline; and a 48px top bar (`--topbar-height`) over
 * the content column carrying the centered command palette and theme toggle.
 *
 * The top-bar search is the ⌘K palette (components/ui/command-palette.tsx),
 * which owns both the global key binding and its pointer trigger.
 *
 * The page header no longer lives in the top bar: `<PageHeader />` renders as
 * the first block of the content column (page-header.tsx), where it has room
 * for the 24/28 H-L title, a wrapping description, and an actions row. The
 * 48px bar is reduced to right-aligned utility chrome.
 *
 * The grouped Analyze/Improve nav is deliberately kept — the Figma flat nav is
 * not adopted (plan.md §10, resolved decision 4).
 *
 * Wrapped once in `<TooltipProvider>` so descendants' tooltips work. Session +
 * project context are provided one level up in `(app)/layout.tsx`, so this
 * component is pure chrome around `children`.
 */
export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <TooltipProvider>
      <div className="bg-background relative flex h-dvh overflow-hidden">
        <BrandAtmosphere variant="app" />
        <aside className="border-border-subtle bg-sidebar relative z-1 hidden w-[var(--sidebar-width)] shrink-0 flex-col border-r transition-[width] md:flex">
          {/* Logo row — matches topbar height */}
          <div className="border-border-subtle flex h-[var(--topbar-height)] shrink-0 items-center gap-3 border-b px-4">
            <LogoMark size={24} />
            <span className="text-foreground font-display text-heading-sm font-semibold">
              CiteLadder
            </span>
          </div>

          <div className="border-border-subtle border-b p-1">
            <ProjectSwitcher />
          </div>

          <div className="sidebar-scroll min-h-0 flex-1 overflow-y-auto px-1.5 py-2">
            <SidebarNav />
          </div>

          <div className="border-border-subtle shrink-0 border-t p-2">
            <UserMenu />
          </div>
        </aside>

        <div className="relative z-1 flex min-w-0 flex-1 flex-col overflow-hidden">
          {/* Top bar with opaque utility chrome. */}
          <header className="border-border-subtle bg-panel sticky top-0 z-20 flex h-[var(--topbar-height)] shrink-0 items-center gap-3 border-b px-4 md:grid md:grid-cols-[minmax(0,1fr)_minmax(0,420px)_minmax(0,1fr)] md:px-6">
            <Link
              href="/projects"
              className="flex shrink-0 items-center gap-2 md:hidden"
              aria-label="CiteLadder command center"
            >
              <LogoMark size={24} />
              <span className="font-display text-foreground font-semibold">CiteLadder</span>
            </Link>
            <div aria-hidden className="hidden md:block" />
            <div className="min-w-0 flex-1 md:w-full md:max-w-105 md:justify-self-center">
              <CommandPalette />
            </div>
            <div aria-hidden className="hidden md:block" />
          </header>

          <main className="content-scroll min-h-0 flex-1 overflow-y-auto pb-16 md:pb-0">
            <div className="mx-auto grid w-full max-w-[var(--content-max-width)] gap-[var(--card-gap)] p-[var(--content-gutter)]">
              <PageHeader />
              {children}
            </div>
          </main>

          <nav
            className="border-border bg-panel fixed inset-x-0 bottom-0 z-30 grid h-16 grid-cols-5 border-t md:hidden"
            aria-label="Primary mobile navigation"
          >
            {[
              { href: '/projects', label: 'Home', icon: Home },
              { href: '/visibility', label: 'Analyze', icon: ChartNoAxesCombined },
              { href: '/opportunities', label: 'Resolve', icon: ListChecks },
              { href: '/content', label: 'Improve', icon: Sparkles },
              { href: '/settings', label: 'Manage', icon: Settings },
            ].map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className="text-muted hover:text-accent-text text-2xs flex min-w-0 flex-col items-center justify-center gap-1 font-medium"
                >
                  <Icon className="size-4" aria-hidden />
                  <span className="truncate">{item.label}</span>
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
    </TooltipProvider>
  );
}
