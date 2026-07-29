# Implementation Plan: Redesign PR Review Remediation (#34 & #33)

This implementation plan addresses valid technical code review findings identified by automated code review tools (Qodo, CodeAnt AI, CodeRabbit) and developer feedback on recently merged PRs:
- **PR #34**: `redesign/marketing-proof-v2` (Merged: 2026-07-29)
- **PR #33**: `refine typography and copy` (Merged: 2026-07-28)

---

## User Review Required

> [!IMPORTANT]
> **Key Architecture Decisions for Approval:**
> 1. **Site Health Rerun Polling Recovery:** Polling in `UrlDetail` will now time out explicitly with user feedback and a "Refresh" action rather than silently stopping on a stale snapshot.
> 2. **Monospace vs Numeric Font Separation:** Code elements (`code`, `pre`, `kbd`, `samp`) will be given a true monospace font stack (`ui-monospace, Consolas, ...`), while metric/chart numbers will continue to use `Google Sans` with `tabular-nums`.
> 3. **Tailwind Class Conflict Configuration:** `tailwind-merge` configuration in `lib/utils.ts` will be extended to recognize custom marketing border-radius utilities (`mkt-lg`, `mkt-sm`, `mkt-md`, `mkt-xl`) so overrides like `rounded-none` take effect properly.

---

## Open Questions

None at this time. All findings have been verified directly against the authoritative codebase source.

---

## Proposed Changes

### 1. Site Health Component & Configuration

Fix silent rerun polling timeout in `UrlDetail`.

#### [MODIFY] [url-detail.tsx](file:///c:/Projects/Searchify/frontend/components/site-health/url-detail.tsx)
- Update `refetchInterval` in `useQuery` for site health page details.
- When `preActivePollCountRef` reaches `RERUN_MAX_PRE_ACTIVE_POLLS` without observing an active rerun status (`pending` or `running`), set `rerunError` to a clear notification: `"Re-audit queued, but status update is taking longer than expected. Refresh to see latest results."`
- Display an explicit `Alert` with a "Refresh" button in `UrlDetail` when `rerunError` is set, allowing manual cache invalidation (`detailQuery.refetch()`).

---

### 2. Frontend Design System & Tailwind Utilities

Fix custom radius class stripping in `tailwind-merge` and separate code monospace fonts from proportional UI fonts.

#### [MODIFY] [utils.ts](file:///c:/Projects/Searchify/frontend/lib/utils.ts)
- Extend `extendTailwindMerge` configuration to register custom border-radius classes (`mkt-lg`, `mkt-sm`, `mkt-md`, `mkt-xl`) under the `borderRadius` conflict group so `rounded-none` correctly overrides `rounded-mkt-lg`.

#### [MODIFY] [wallpaper-panel.tsx](file:///c:/Projects/Searchify/frontend/components/marketing/scenes/wallpaper-panel.tsx)
- Ensure `WallpaperPanel` accepts and respects `rounded={false}` or explicit `className` overrides cleanly.

#### [MODIFY] [globals.css](file:///c:/Projects/Searchify/frontend/app/globals.css)
- Separate `--font-code-family` (a true monospace font stack: `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace`) from `--font-mono-family` / `--font-primary-family`.
- Update `code`, `pre`, `kbd`, `samp` selectors to use `--font-code-family` so code blocks retain character column alignment, while metrics and tabular data continue using Google Sans with `tabular-nums`.

---

### 3. Traffic Dashboard UX

Fix suppressed connection notice on empty traffic dashboards.

#### [MODIFY] [traffic-screen.tsx](file:///c:/Projects/Searchify/frontend/components/traffic/traffic-screen.tsx)
- Include `{syncNotice ? <Alert tone="info">{syncNotice}</Alert> : null}` in the empty state render branch (`empty && range === 'latest'`).
- Ensure users who attempt a sync on an empty dashboard receive visible connection status feedback when zero active connections are returned.

---

### 4. Documentation & Design System Test Guards

Update stale font alias comments and enforce exact two-face font loading.

#### [MODIFY] [check-design-tokens.mjs](file:///c:/Projects/Searchify/frontend/scripts/check-design-tokens.mjs)
- Update font-mkt-display description comment from Geist alias to Plus Jakarta Sans.

#### [MODIFY] [layout.tsx](file:///c:/Projects/Searchify/frontend/app/(marketing)/layout.tsx)
- Update marketing layout font comment to reference Plus Jakarta Sans instead of Geist.

#### [MODIFY] [globals.test.ts](file:///c:/Projects/Searchify/frontend/app/globals.test.ts)
- Update typography tests to assert that `layout.tsx` imports and configures the exact two font faces (`Google Sans` and `Plus Jakarta Sans`).

---

## Verification Plan

### Automated Tests
- Run `pnpm test` / `npm test` inside `frontend/` to run all frontend test suites (`globals.test.ts`, `url-detail.test.tsx`, `traffic-screen.test.tsx`, `wallpaper-panel.test.tsx`).
- Run `node frontend/scripts/check-design-tokens.mjs` to verify design system token compliance.
- Run `node frontend/scripts/check-frontend-architecture.mjs` to verify architecture policies.
- Run `npx tsc --noEmit` in `frontend/` to ensure full TypeScript type safety.

### Manual Verification
- **UrlDetail Rerun Polling:** Trigger a rerun on a site health URL detail page with slow backend transition; verify the timeout message appears with a working "Refresh" button rather than silently stopping.
- **WallpaperPanel Border Radius:** Verify the `Shift` section and `AuthBrandPanel` render edge-to-edge without rounded corner insets when `rounded-none` is passed.
- **Monospace Code Elements:** Inspect `<pre><code>` blocks and command palette keys to confirm true monospaced character column alignment.
- **Traffic Empty Dashboard Sync:** Click "Sync now" on an empty traffic dashboard without active connections and verify the sync notice alert appears clearly above the empty state card.
