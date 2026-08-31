'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';

import { RouteContent } from '@/components/providers/product-motion-provider';
import { CommandPalette } from '@/components/ui/command-palette';
import { LogoMark } from '@/components/ui/logo-mark';
import { TooltipProvider } from '@/components/ui/tooltip';

import { AgentSheet } from './agent-sheet';
import { PageHeader } from './page-header';
import { ProjectSwitcher } from './project-switcher';
import { MobilePrimaryNavigation, MobileStationNavigation, SidebarNav } from './sidebar-nav';
import { UserMenu } from './user-menu';

/**
 * AppShell — the authenticated application chrome.
 *
 * Geometry: a 236px left sidebar (`bg-sidebar`, `--sidebar-width`) stacked as
 * logo row → project switcher → grouped nav → user card, each
 * band separated by a hairline; and a 52px top bar (`--topbar-height`) over
 * the content column carrying the centered command palette and Agent trigger.
 */
export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <TooltipProvider>
      <div className="product-app bg-background relative flex h-dvh overflow-hidden">
        <aside className="border-border-subtle bg-sidebar relative z-1 hidden w-[var(--sidebar-width)] shrink-0 flex-col border-r transition-[width] md:flex">
          {/* Logo row — matches topbar height */}
          <div className="border-border-subtle flex h-[var(--topbar-height)] shrink-0 items-center border-b px-4">
            <LogoMark size={22} />
          </div>

          <div className="border-border-subtle border-b p-1.5">
            <ProjectSwitcher />
          </div>

          <div className="sidebar-scroll min-h-0 flex-1 overflow-y-auto px-2 py-2.5">
            <SidebarNav />
          </div>

          <div className="border-border-subtle shrink-0 border-t p-2">
            <UserMenu />
          </div>
        </aside>

        <div className="relative z-1 flex min-w-0 flex-1 flex-col overflow-hidden">
          {/* Top bar with frosted glassmorphism utility chrome. */}
          <header className="border-border-subtle bg-background/80 sticky top-0 z-20 flex h-[var(--topbar-height)] shrink-0 items-center justify-between gap-3 border-b px-[var(--content-gutter)] backdrop-blur-md md:grid md:grid-cols-[minmax(0,1fr)_minmax(0,440px)_minmax(0,1fr)]">
            <div className="flex items-center gap-2 md:hidden">
              <Link
                href="/projects"
                className="flex shrink-0 items-center gap-2"
                aria-label="CiteLadder command center"
              >
                <LogoMark size={20} />
              </Link>
            </div>
            <div aria-hidden className="hidden md:block" />
            <div className="min-w-0 flex-1 md:w-full md:max-w-110 md:justify-self-center">
              <CommandPalette />
            </div>
            <div className="flex items-center justify-end gap-2.5">
              <AgentSheet />
            </div>
          </header>

          <main
            id="main"
            className="content-scroll safe-bottom min-h-0 flex-1 overflow-y-auto pb-20 md:pb-0"
          >
            <MobileStationNavigation />
            <div className="mx-auto grid w-full max-w-[var(--content-max-width)] grid-cols-[minmax(0,1fr)] gap-0 p-[var(--content-gutter)]">
              <PageHeader />
              <RouteContent>{children}</RouteContent>
            </div>
          </main>

          <MobilePrimaryNavigation />
        </div>
      </div>
    </TooltipProvider>
  );
}
