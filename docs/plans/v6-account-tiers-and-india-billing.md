# Account tiers + India billing integration plan

> **Status: DRAFT FOR OWNER APPROVAL — planning only; nothing in this document is
> implemented.** Prepared 2026-07-26. This plan assumes the clarified commercial rule:
> **one user owns one subscription**. Workspaces remain the authorization and data boundary,
> and agency/enterprise users may place multiple workspaces under the same billing account.
>
> Depends on: [`v5-free-tier-cost-and-latency.md`](v5-free-tier-cost-and-latency.md) for the
> audit capabilities that the tiers unlock. Companion contracts:
> [`backend-architecture.md`](../backend-architecture.md),
> [`frontend-architecture.md`](../frontend-architecture.md), and
> [`invariants.md`](../invariants.md).

## 1. Outcome

Build a provider-neutral subscription domain that:

1. creates a Free billing account and entitlement when a user registers;
2. restores the effective tier during post-login application bootstrap without putting a
   mutable tier into the JWT;
3. permits at most one live subscription per user-owned billing account;
4. lets every owned workspace inherit that subscription, while an invited member sees the
   entitlement of the workspace they are currently using;
5. provisions and revokes Paid capabilities from verified payment-provider webhooks; and
6. can use Razorpay for an India launch and Stripe for eligible international sales without
   leaking provider concepts into audit, site-health, or frontend feature logic.

The initial commercial vocabulary is deliberately only `free | paid`. Display names, prices,
currencies, and provider price/plan ids are configuration, not persisted feature checks.

## 2. Decisions made by this plan

### 2.1 Subscription ownership

`User` does **not** gain a `plan` column. A new `BillingAccount` is one-to-one with the user
who owns it (`owner_user_id` unique) and owns at most one current subscription. Each workspace
has one billing sponsor:

```text
User 1──1 BillingAccount 1──0..n WorkspaceBillingLink n──1 Workspace
                 │
                 ├── BillingSubscription history (at most one current)
                 └── AccountEntitlement current projection
```

- A normal user gets one personal workspace linked to their billing account.
- An agency owner can create several workspaces linked to the same billing account and still
  has only one subscription.
- An invited member's own subscription is irrelevant while viewing an agency workspace; the
  workspace billing link determines the effective capability.
- A future enterprise contract can sponsor a workspace through an organization-owned billing
  account without changing project authorization. That extension is not part of this build.

This does not weaken invariant 5: project reads/writes remain authorized by
`require_workspace_member` and filtered by `workspace_id`. Billing ownership is never an
alternate route to project data.

### 2.2 Login-to-tier behavior

Authentication proves identity; it does not grant a tier. The JWT continues to contain only
stable session identity. After `GET /auth/me` succeeds, the app fetches the billing summary
and, once an active workspace is known, its effective entitlement.

Do not encode `tier_key`, subscription status, quota, or capability revision in the cookie/JWT:
webhook changes and downgrades must take effect without waiting for a session to expire.

### 2.3 Payment-provider recommendation for an Indian business

Use a provider abstraction, but launch providers in this order:

1. **Razorpay for INR/India customers.** Its subscription product documents cards, UPI
   AutoPay, and eMandate, automated billing, retries, invoices, and subscription webhooks.
   This is the lower-risk India launch route, subject to CiteLadder's account/KYC and requested
   payment methods being activated.
2. **Stripe for international customers only after CiteLadder receives an Indian Stripe
   account invitation and export payments are enabled.** Stripe is a good technical fit and
   remains the preferred international provider, but it is currently invite-only in India,
   so it cannot be the only go-live dependency.
3. Do not silently fail over a subscription between providers. A customer has one provider
   for one subscription lifecycle. Migration is an explicit cancel/re-subscribe operation.

Stripe's current India documentation says:

- new India accounts are invite-only and focused on selected businesses with international
  expansion;
- an Indian legal business (not an individual) and export transaction data are required for
  international payments;
- India recurring payments are a public-preview RBI e-mandate flow; India-issued cards/UPI
  require mandate handling and advance debit notification, with documented collection and
  retry constraints.

Therefore, Stripe remains in the design and test suite but cannot be declared the production
provider until the account-approval and live-payment gate in Task 0 passes.

Official sources checked 2026-07-26:

- [Stripe: Accept international payments from India](https://docs.stripe.com/india-accept-international-payments)
- [Stripe: India recurring payments](https://docs.stripe.com/india-recurring-payments)
- [Stripe: subscription lifecycle](https://docs.stripe.com/billing/subscriptions/overview)
- [Razorpay: Subscriptions](https://razorpay.com/docs/payments/subscriptions/)
- [Razorpay: webhooks](https://razorpay.com/docs/webhooks/)

Provider availability, fees, methods, and regulatory requirements can change. Recheck them
when Task 0 starts; this document is technical planning, not legal or tax advice.

## 3. Product contract

### 3.1 Internal tiers and effective capabilities

Only the entitlement domain translates commercial tiers into capabilities. Feature code asks
questions such as `audit.web_search`, `audit.scheduling`, or `site_health.full_inventory`; it
does not compare marketing names.

| Commercial tier | Initial capability mapping |
|---|---|
| `free` | V5 Free audit profile; existing Site Health `free` capability |
| `paid` | V5 Paid audit profile; existing Site Health `starter` capability |

The existing `WorkspaceSiteHealthEntitlement` is a subsystem quota projection, not a second
billing source of truth. Billing entitlement changes synchronize its capability using the
existing `set_entitlement()` service. Later tiers can map to new subsystem capability keys
without renaming historical subscriptions.

### 3.2 Subscription state mapping

Normalize provider-specific states into:

`pending | trialing | active | past_due | cancel_scheduled | cancelled | unpaid | expired`

Recommended access policy (all durations config-owned):

| State | Effective entitlement |
|---|---|
| no subscription / `pending` / `expired` / `unpaid` | Free |
| `trialing` / `active` | Paid |
| `past_due` | Paid during a 3-day grace period, then Free |
| `cancel_scheduled` | Paid through `current_period_end`, then Free |
| `cancelled` | Free unless a paid-through date is still in the future |

The provider webhook is authoritative. A browser checkout success callback never upgrades an
account. For a critical return-page experience, fetch the provider subscription server-side,
then apply the same idempotent projection path used by a webhook.

### 3.3 Upgrade, downgrade, and history rules

- Free → Paid becomes effective only after confirmed initial payment or an explicitly valid
  trial state.
- Paid → Free is normally end-of-period; payment failure follows the grace policy.
- Existing audits/crawls retain their frozen configuration and evidence after downgrade.
- Downgrade blocks new paid work and future scheduled dispatches; it never mutates or deletes
  prior artifacts.
- Refunds do not automatically revoke time unless the configured refund policy says so.
- One billing account cannot have simultaneous live Stripe and Razorpay subscriptions.

## 4. Persistence design

All ids are UUIDs. External provider ids are opaque strings and always constrained with their
provider key.

### 4.1 `BillingAccount`

- `id`, `owner_user_id` (unique FK), `status`, `created_at`, `updated_at`.
- No payment-provider customer id here: one account may retain historical identities from
  more than one provider.

### 4.2 `WorkspaceBillingLink`

- `id`, `workspace_id` (unique FK), `billing_account_id` (FK), `created_at`.
- Created atomically with a personal workspace. Agency-created workspaces link to the creating
  owner's billing account.
- This link selects capabilities only; it grants no membership or data access.

### 4.3 `BillingCustomer`

- `id`, `billing_account_id`, `provider`, `external_customer_id`, timestamps.
- Unique `(provider, external_customer_id)` and `(billing_account_id, provider)`.
- Store only necessary billing identity; never return it in normal session DTOs.

### 4.4 `BillingSubscription`

- `id`, `billing_account_id`, `billing_customer_id`, `provider`.
- `external_subscription_id`, `external_price_id`, internal `tier_key`, `cadence`, `currency`.
- normalized `status`, `current_period_start/end`, `cancel_at_period_end`, `ended_at`.
- `provider_state_version` or last provider event timestamp for stale-event rejection.
- unique `(provider, external_subscription_id)` and a DB-enforced rule allowing at most one
  current subscription per billing account.
- Rows retain history; a provider migration creates a new row rather than overwriting identity.

### 4.5 `AccountEntitlement`

- exactly one mutable current projection per billing account;
- `tier_key`, `capability_revision`, `source_subscription_id` (nullable for Free),
  `effective_from`, `paid_through`, `grace_until`, and timestamps;
- locked `FOR UPDATE` whenever billing changes apply so tier and subsystem projections move
  together in one transaction.

### 4.6 `BillingWebhookEvent` and `BillingCheckoutAttempt`

- Webhook event: provider, external event id, event type, payload SHA-256, received/processed
  timestamps, result/error code; unique `(provider, external_event_id)`.
- Store a bounded, allow-listed event summary, not the entire provider payload. Webhooks often
  contain customer PII. Never log request bodies, signatures, API keys, or checkout secrets.
- Checkout attempt: billing account, provider, internal tier/cadence/currency, opaque external
  checkout/subscription reference, status, expiry, idempotency key. It supports reconciliation
  but does not itself grant access.

Greenfield migration policy applies: update models and `0001_initial`; do not add `0002`.

## 5. Configuration and provider boundary

Create `app/core/config/billing.py` as the only owner of:

- tier/capability catalog and grace periods;
- supported billing countries/currencies/cadences;
- server-side price/plan id mapping for each provider and environment;
- checkout return URLs and portal behavior;
- webhook tolerance, timeouts, and retry settings;
- Stripe and Razorpay credentials/secret names.

Secrets stay in server environment variables and never enter response DTOs. Unlike BYOK answer
engine keys, these are CiteLadder's own infrastructure credentials.

Define a `BillingProvider` protocol under `connectors/billing/` with operations equivalent to:

- `create_customer`, `create_checkout`, `fetch_subscription`, `create_portal_or_manage_url`;
- `cancel_subscription`; and
- `verify_and_parse_webhook` returning a provider-neutral event.

Implement `RazorpayBillingProvider` and `StripeBillingProvider` behind a factory. Domain code
owns lifecycle rules; adapters only translate provider APIs. Use hosted checkout so CiteLadder
never receives card or UPI credentials.

Provider routing is server-owned. **Country comes from the server's own billing profile, never
from the request** — a client-supplied `billing_country` would let a caller pick its own tax
and currency treatment, so the field does not exist in the API (§6):

- verified Indian billing address + INR catalog → Razorpay;
- verified non-Indian billing address + enabled export catalog → Stripe, only when the
  production readiness flag is true;
- unsupported routes return a clear error; the browser cannot select an arbitrary provider or
  price id.

A profile whose country is still **provisional** (self-declared, not yet confirmed by the
provider) may open checkout, but the resulting subscription and price route are only retained
once the provider-confirmed billing address matches the route that was used. On a mismatch the
subscription is not activated against that route: the webhook handler flags the account for
re-routing and the entitlement stays at its previous tier rather than being granted on an
unverified country.

## 6. API contract

Add `/api/v1/billing` routes. All customer-facing routes require authentication; routes that
change billing require the billing-account owner. Workspace entitlement reads also require
`require_workspace_member`.

| Method | Route | Contract |
|---|---|---|
| `GET` | `/billing/me` | Own billing summary: tier, normalized state, cadence, paid-through/grace dates, available checkout route; no external ids/secrets |
| `POST` | `/billing/checkout` | `{tier_key:"paid", cadence}` → hosted checkout URL; idempotent and rejects an existing live subscription. **The body carries no country and no price id** — both are resolved server-side from the billing profile (see §5) |
| `POST` | `/billing/manage` | Hosted management/portal URL or provider management action |
| `POST` | `/billing/cancel` | End-of-period cancellation; idempotent |
| `GET` | `/workspaces/{workspace_id}/entitlements` | Effective tier + capability booleans/limits + revision for the active workspace |
| `POST` | `/billing/webhooks/stripe` | Unauthenticated transport endpoint; signature verification is mandatory before parsing |
| `POST` | `/billing/webhooks/razorpay` | Same rules for Razorpay |

Webhook responses acknowledge duplicates. Invalid signatures return 400 and do not persist a
processed event. Valid but temporarily unprocessable events return a retryable 5xx; permanent,
safe-to-ignore events are recorded and acknowledged.

## 7. Frontend contract

### 7.1 Session bootstrap

Keep `SessionGuard` responsible for `GET /auth/me`. Add an `EntitlementProvider` inside the
authenticated shell:

1. fetch `/billing/me` after session success;
2. fetch effective workspace entitlements after `ProjectProvider` resolves the workspace;
3. keep the last successful entitlement on transient 5xx/network failures, but fail closed for
   starting paid-only work when no entitlement has ever loaded;
4. invalidate both queries after checkout return, workspace change, or a manage/cancel action.

Tier data is not stored in localStorage and is not trusted from checkout query parameters.

### 7.2 Billing UI

- Add Billing under authenticated Settings: current plan, subscription status, renewal/end
  date, upgrade/manage/cancel actions, and payment-pending/grace states.
- Checkout return pages say “Confirming payment” until the backend confirms the webhook/fetch;
  never optimistically show Paid.
- Paid-only controls stay visible with an upgrade explanation where useful; the backend remains
  the authoritative enforcement point.
- Replace the current four-tier, USD-only, “BYOK platform fee” marketing matrix with the
  approved two-tier catalog in the same implementation change. Do not publish INR/USD prices
  until Task 0 approves tax treatment and exact amounts.
- Keep browser calls same-origin under `/api/v1`.

## 8. India operational gates (Task 0, before coding checkout)

The owner and an India-qualified accountant/legal adviser must resolve and record:

1. CiteLadder legal entity type, bank account, PAN, GST registration/treatment, invoice fields,
   and whether displayed prices include GST.
2. Domestic SaaS place-of-supply and GST invoicing; export-of-services documentation, LUT/IGST
   approach, foreign inward-remittance evidence, purpose code, and whether an IEC is required
   for CiteLadder's facts.
3. Refund/cancellation policy, Terms, Privacy notice, recurring-debit consent copy, and support
   contact shown in checkout.
4. Final Free/Paid names, INR and international prices, monthly/annual cadence, trial policy,
   grace policy, and whether international cards are required at launch.
5. Razorpay live KYC plus Subscriptions, UPI AutoPay/eMandate, webhooks, and international
   payments activation as applicable.
6. Stripe India invitation, exports activation, live settlement currency, supported recurring
   payment methods, and a real test settlement. If not approved, Stripe stays disabled.

No code should infer tax residency from IP address. Collect a billing country/address through
hosted checkout and rely on provider-generated tax invoices only after accounting review says
they meet CiteLadder's obligations.

## 9. Implementation task graph

### Task 0 — commercial, tax, and provider readiness

- Complete §8 and save the signed-off catalog in a short decision record.
- Create provider sandbox accounts, then production accounts; record enabled capabilities, not
  credentials.
- Run one domestic INR recurring-payment lifecycle in test mode for Razorpay.
- Run international Stripe tests only if the India account is approved.
- **Exit:** exact prices, routes, tax display, lifecycle policy, and production provider order
  are approved. No placeholder claims remain on `/pricing`.

### Task 1 — canonical billing persistence and registration bootstrap

Owning subsystems: `models`, `domain/billing`, `domain/auth`, `domain/workspaces`.

- Add the §4 models and relationships; update the squashed bootstrap migration.
- Extend registration/personal-workspace creation so User + BillingAccount + Free entitlement +
  workspace billing link commit atomically.
- Add an idempotent backfill service/CLI for existing users and workspaces. Login may repair a
  missing billing bootstrap, but normal reads must not create competing subscriptions.
- Add DB constraints for one account per owner, one sponsor per workspace, unique provider
  identities/events, and one current subscription.
- **Tests:** concurrent registration/backfill, rollback atomicity, association isolation,
  duplicate subscription/event constraints.

### Task 2 — entitlement resolver and subsystem mappings

Owning subsystem: `domain/entitlements` (one commercial source) plus thin subsystem mappings.

- Implement account and effective-workspace entitlement reads.
- Implement the locked, monotonic `capability_revision` transition.
- Synchronize existing Site Health capability through its service; expose the V5 audit profile.
- Define fail-closed behavior for missing/corrupt sponsorship and stale grace dates.
- **Tests:** personal/agency/invited-member resolution, upgrade/downgrade, stale events,
  downgrade preserving historical artifacts.

### Task 3 — billing provider protocol and sandbox adapters

Owning subsystem: `connectors/billing`.

- Add protocol, neutral DTOs/errors, factory, shared safe HTTP client, Stripe adapter, Razorpay
  adapter, and fake adapter for tests.
- Build only hosted checkout/manage flows. Use idempotency keys on provider mutations.
- Verify webhook signatures against the unmodified raw body with constant-time library helpers.
- Allow-list safe errors; redact request/response bodies and credentials.
- **Contract tests:** equivalent neutral events for create/renew/fail/cancel/refund; timeout,
  429, duplicate, invalid-signature, and provider-reordered event cases.

### Task 4 — webhook-owned lifecycle projection

Owning subsystem: `domain/billing` + thin `api/billing.py`.

- Persist verified event identity before applying it; lock the subscription/account entitlement;
  reject stale state; update subscription + entitlement + subsystem mappings atomically.
- Make replay and provider retry safe. Add a bounded reconciliation command for events that
  failed after signature verification.
- Emit structured event ids/status transitions only—no PII payloads.
- **Tests:** at-least-once delivery, out-of-order renewal/cancel, late success after browser
  close, grace expiry, replay, cross-account external-id collision, webhook/checkout race.

### Task 5 — billing and entitlement APIs

- Implement §6 with strict DTOs and owner/member dependencies.
- Choose provider and external plan id only on the server from config.
- Return stable error codes: `billing_not_owner`, `subscription_exists`,
  `billing_route_unavailable`, `payment_pending`, and `entitlement_unavailable`.
- Rate-limit checkout creation and webhook endpoints using config-owned bounds.
- **Tests:** unauthenticated, invited non-owner, cross-workspace, arbitrary price/provider
  injection, duplicate idempotency key, and secret/PII non-disclosure.

### Task 6 — login bootstrap, Settings, checkout, and marketing UI

Owning frontend subsystems: `shell+auth`, `API-contract`, `settings`, `marketing`.

- Add strict Zod schemas/API methods/query keys and `EntitlementProvider`.
- Add Billing settings and pending/success/cancel UX; invalidate entitlement queries safely.
- Gate controls for clarity but retain backend enforcement.
- Replace four-tier pricing content/tests with the approved two-tier catalog and correct
  BYOK/retrieval claims from V5.
- **Tests:** register/login Free bootstrap, workspace switching, invited agency entitlement,
  payment pending, webhook-confirmed upgrade, grace/downgrade, 401 versus transient 5xx, and
  same-origin requests.

### Task 7 — rollout and operations

- Deploy webhook endpoints before enabling checkout and register production webhook secrets.
- Replay sandbox fixtures in staging; reconcile provider dashboards against DB projections.
- Backfill all accounts as Free, enable read-only entitlement UI, then enable Razorpay checkout
  for an allow-list, then general India availability; enable Stripe separately after its gate.
- Alert on invalid-signature spikes, unprocessed events, stale pending checkout, entitlement /
  provider disagreement, duplicate active subscriptions, and grace expiries.
- Publish cancellation/refund/support processes and a provider outage runbook.

## 10. Verification commands

Focused files should be chosen as tasks land; expected commands include:

```bash
# backend/
uv run pytest tests/unit/test_billing_config.py tests/unit/test_billing_providers.py -q
uv run pytest tests/component/test_billing_models.py tests/component/test_billing_api.py -q
uv run pytest tests/component/test_billing_webhooks.py tests/component/test_auth_api.py -q
uv run ruff check .
uv run alembic upgrade head

# frontend/
pnpm test -- lib/api/billing.test.ts
pnpm test -- components/settings/billing-settings.test.tsx
pnpm test -- "app/(marketing)/pricing/page.test.tsx"
pnpm lint
pnpm build
```

Use sandbox clocks/webhook fixtures; CI must never call a live payment provider.

## 11. Definition of done

- A newly registered user has exactly one Free billing account and one subscription slot.
- The user's owned workspaces inherit that tier; invited users see the active workspace's tier.
- Login/session refresh reflects webhook-driven tier changes without reissuing the JWT.
- Only verified, idempotently processed provider state can grant Paid access.
- Razorpay completes create → renew → fail/grace → cancel test lifecycles; Stripe does the same
  before it is enabled.
- No browser-selected provider/price can bypass the server catalog; no payment or BYOK secret,
  signature, full webhook body, or external customer id appears in public DTOs/logs.
- Audit and Site Health enforce capabilities server-side and preserve frozen historical runs.
- Pricing copy, checkout currency/tax copy, and actual entitlements agree.

## 12. Explicit non-goals

- Usage-based billing, audit overages, coupons, credits, seat billing, reseller billing, and
  multiple simultaneous subscriptions.
- Building a custom card/UPI form or storing payment credentials.
- Automatically migrating an active subscription between Razorpay and Stripe.
- Organization-owned enterprise billing, purchase orders, or manual invoicing beyond a future
  extension point.
- Platform-funded answer-engine keys; audit execution remains BYOK unless a separate security,
  abuse, and unit-economics plan explicitly replaces that contract.
