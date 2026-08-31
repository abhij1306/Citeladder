# Authenticated UI component system

This is the active map for authenticated product controls. HeroUI is a behavior
and state-quality reference, not a runtime dependency. CiteLadder owns the
visual contract and builds it from Radix primitives, Tailwind tokens, Motion,
React Hook Form, Zod, and TanStack Query.

## Capability map

| Capability | Decision | CiteLadder owner |
|---|---|---|
| Button, Card, Input, Textarea, Field | Deepen | `frontend/components/ui/` |
| Dropdown Menu, Dialog, Drawer, Tooltip | Deepen | `frontend/components/ui/` Radix wrappers |
| Table, Badge, Alert, Skeleton, progress, empty state, pagination, segmented control | Deepen | `frontend/components/ui/` |
| Select | Add | `components/ui/select.tsx` |
| Search field | Add | `components/ui/search-field.tsx` |
| Popover | Add | `components/ui/popover.tsx` |
| Tabs | Add | `components/ui/tabs.tsx` |
| Disclosure | Add | `components/ui/disclosure.tsx` |
| Checkbox and radio group | Add | `components/ui/checkbox.tsx`, `radio-group.tsx` |
| Toast | Add | `components/ui/toast.tsx`; transient success only |
| Pressable | Add | `components/ui/pressable.tsx`; rows/cards without button chrome |
| Clipboard action | Add | `components/ui/copy-button.tsx` |
| Command palette, Market Select, CSV import | Specialized | Keep narrow public interfaces; compose shared primitives where useful |
| Cursor/table pagination, resizable workspaces | Specialized | Existing feature owners |
| Color controls, OTP, sliders, calendars/date pickers, avatars | Defer | No current product use |

Controls expose default, hover, pressed, focus, selected, pending, disabled,
invalid, success, and destructive states when the capability needs them. App
geometry remains 6px controls, 8px cards, and 10px overlays.

## State ownership

- TanStack Query owns server state. Query records are never copied into local
  state. Selection stores stable IDs and derives records from current query
  data. Paginated and filtered reads retain previous data during background
  fetching and mark the surface busy; skeletons are initial-load only.
- The typed URL-state owner in `frontend/lib/navigation/url-state.ts` owns
  shareable shallow state. Visible tabs, filters, pagination, and record
  selection use push history. Defaults, canonicalization, and callback cleanup
  use replace history. Unrelated parameters survive and owning filter changes
  clear their cursors.
- Local state owns drafts, focus intent, temporary overlay interaction, and
  multi-step workflow reducers. Forms use React Hook Form and Zod. Overlay
  openness derives from selected IDs where that is the actual state.

## Motion ownership

`ProductMotionProvider` lazy-loads Motion features for authenticated routes and
honors the user's reduced-motion preference. Route content and tab selection are
immediate so navigation never flashes through an opacity transition. Overlays
and disclosures retain spatially symmetric entry and exit. Input, focus,
navigation, and server updates never wait for animation. Large tables, polling
metrics, and charts do not reanimate ornamentally.

## Enforcement

The design-system policy rejects production native selects, raw authenticated
buttons outside shared UI owners, direct feature-level Radix imports, and
cosmetic Button overrides. Feature call sites may supply semantic layout only.
Superseded tab recipes and native-select styling paths are removed after their
consumers move.
