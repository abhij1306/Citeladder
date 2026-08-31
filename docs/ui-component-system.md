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
| Tabs | Add | `components/ui/tabs.tsx` |
| Checkbox and radio group | Deepen | `components/ui/checkbox.tsx`, `radio-group.tsx`; indeterminate and chip presentation included |
| Toast | Add | `components/ui/toast.tsx`; transient success only |
| Pressable | Add | `components/ui/pressable.tsx`; rows/cards without button chrome |
| Clipboard action | Add | `components/ui/copy-button.tsx` |
| Command palette, Market Select, CSV import | Specialized | `csv-import.tsx` owns file selection, reset/reselection, pending state, and accessible labeling; domain parsers remain feature-owned |
| Cursor/table pagination, resizable workspaces | Specialized | Existing feature owners |
| Color controls, OTP, sliders, calendars/date pickers, avatars | Defer | No current product use |
| Generic disclosure and donut | Removed | No production consumers; domain tree/table expanders retain their own behavior |

Controls expose default, hover, pressed, focus, selected, pending, disabled,
invalid, success, and destructive states when the capability needs them. App
geometry remains 6px controls, 8px cards, and 10px overlays.

`Input` owns optional `startContent` and `endContent` adornments and its shared
frame. `containerClassName` targets that frame; `className` continues to target
the native input and the native ref is preserved. `Textarea` has its own module
with no compatibility re-export. `Checkbox` requires either a visible `label`
or an `aria-label`, and its semantic control owns a control-height hit target
around the compact mark. `RadioGroup` retains Radix mutual exclusion and keyboard
semantics in both standard and chip presentations; grouped chip rows remain one
radio group. `SearchField` composes the Input anatomy rather than defining another
field frame. `Drawer` owns modal padding, footer separation, and focus return just
as `Dialog` does. Opportunity filters use the existing Dropdown radio-menu owner;
the former single-consumer Popover wrapper was removed.

## Ownership boundary

Shared primitives own geometry, tokens, accessibility, interaction states, and
motion. Domain wrappers own business logic, factual copy, data translation, and
conditional behavior. A consolidation must not introduce a second owner for an
existing responsibility: modify or delete the current owner first. A new shared
module needs two production consumers unless it replaces an existing owner.

HeroUI v3 source, styles, and stories are visual references for spacing,
alignment, hierarchy, state contrast, focus, and micro-transitions. HeroUI is
not installed, its component interfaces are not copied, and it is not an
architectural owner.

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
  multi-step workflow reducers. Complex forms use React Hook Form and Zod where
  they already own validation. Small searches, filters, billing state,
  schedules, and transient interactions remain local when a migration would not
  remove duplicated validation. Overlay
  openness derives from selected IDs where that is the actual state.

## Motion ownership

`ProductMotionProvider` lazy-loads Motion features for authenticated routes and
honors the user's reduced-motion preference. Route content and tab selection are
immediate so navigation never flashes through an opacity transition. Overlays
retain spatially symmetric entry and exit. Input, focus,
navigation, and server updates never wait for animation. Large tables, polling
metrics, and charts do not reanimate ornamentally.

## Enforcement

The design-system policy rejects production native inputs, textareas, selects,
and raw authenticated buttons outside shared UI owners, direct feature-level Radix imports, and
cosmetic Button overrides. Feature call sites may supply semantic layout only.
Superseded tab recipes and native-select styling paths are removed after their
consumers move.
