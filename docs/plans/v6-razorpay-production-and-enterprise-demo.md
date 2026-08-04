# Razorpay production billing + enterprise demo implementation plan

> **Status: DISABLED-BY-DEFAULT FOUNDATION IMPLEMENTED; LIVE WIRING PENDING OWNER INPUTS.** Payment-domain code,
> sandbox tooling, and UI may be implemented before business/KYC inputs are ready,
> but no live Razorpay plan, webhook, or checkout may be enabled until the owner
> completes the blocking go-live inputs in
> [`../operations/razorpay-and-demo-owner-requirements.md`](../operations/razorpay-and-demo-owner-requirements.md).
> Prepared and source-checked 2026-07-26.
>
> This plan narrows the provider rollout in
> [`v6-account-tiers-and-india-billing.md`](v6-account-tiers-and-india-billing.md):
> Razorpay is the only launch payment provider. Stripe remains a future adapter,
> not a launch dependency. The provider-neutral entitlement boundary and all V6
> security, workspace, provenance, and immutable-history rules still apply.

## 1. Approved-direction summary

- Launch India-first self-serve billing through **Razorpay Subscriptions**.
- Keep the internal commercial capability vocabulary `free | paid`.
- Treat Free as an internal entitlement; do not create a zero-value Razorpay plan.
- Map Paid to the existing Starter capability surface and the existing public
  commitment of **$49/month before applicable tax**.
- Use a two-region launch price book: verified India billing profiles use an INR
  plan with GST added; all other supported countries use a USD plan. The INR base
  is calculated once during plan provisioning from `$49` and an operator-supplied,
  versioned USD/INR rate, rounded in minor units, then frozen into the Razorpay
  Plan. It is never recalculated for an active subscription.
- Do not infer region from IP. Country is recorded in the server-owned billing
  profile and later verified against provider billing evidence.
- Additional native-currency plans (EUR/GBP/etc.) are an extension of the price
  book, not a live-FX conversion during checkout.
- Keep Enterprise sales-assisted. It is not a Razorpay SKU and does not grant an
  entitlement until a future contract/manual-provisioning plan is approved.
- Make `/demo` the stable internal enterprise funnel. Every “Book a demo” or
  Enterprise sales CTA routes there through the existing centralized
  `DEMO_HREF`; `/enterprise` remains the product explanation page.
- Use Razorpay-hosted subscription authorization (`short_url`) so CiteLadder does
  not receive card, UPI VPA, bank-account, or mandate credentials.
- Only verified Razorpay webhook state can grant Paid. Checkout return parameters,
  redirects, and client state never grant access.

## 2. Why the production design uses Razorpay this way

Razorpay's current integration guide defines the lifecycle as: create a reusable
Plan, create a Subscription, then authorize it through Standard Checkout. The
Subscriptions API returns a `short_url` for authorization, and requires the
subscription to be bounded by `total_count` or `end_at`. CiteLadder will use that
hosted URL and a config-owned cycle count rather than embedding a card form.

Razorpay webhooks are at-least-once and may arrive out of order. The unique
`x-razorpay-event-id` header is the dedupe key. The request signature is an HMAC
SHA-256 over the **unchanged raw body** using the webhook secret. Razorpay expects
a successful response promptly (its best-practices page describes a five-second
response window), retries failed delivery with exponential backoff for up to 24
hours, and can disable a persistently failing webhook. Those are core state-machine
requirements, not optional hardening.

Razorpay documents Cards, UPI AutoPay, and eMandate for Subscriptions, but actual
availability and mandate limits depend on account activation, bank/app/network,
business category, and enabled products. The UI must only claim methods confirmed
in CiteLadder's activated live account.

## 3. Commercial catalog and plan provisioning

### 3.1 Catalog contract

The launch catalog is:

| Product | Billing object | Current decision |
|---|---|---|
| Free | No Razorpay object | `$0`, internal `free` entitlement |
| Paid monthly — international | Razorpay USD Plan | `$49/month`, tax handled per approved international route |
| Paid monthly — India | Razorpay INR Plan | `$49` converted once at provisioning with a versioned operator rate, plus config-owned GST; both are frozen |
| Annual Paid | None at launch | Deferred unless the owner supplies an exact annual amount and policy |
| Enterprise | No Razorpay object | Custom sales-assisted agreement through `/demo` |

The backend catalog owner will be `app/core/config/billing.py`. It will define a
versioned immutable catalog entry with: internal tier, public name, cadence,
currency, amount in minor units, Razorpay period/interval, subscription cycle
count, grace duration, checkout expiry, and environment-specific Razorpay plan id.
Service code must not contain any of those values.

Razorpay International Payments and international subscription cards require
separate merchant-account activation. The international route stays unavailable
until that readiness flag and the USD plan id are configured. UPI AutoPay and
eMandate remain INR-only; international-currency Subscriptions are card-only.

Public marketing copy remains owned by the frontend marketing-content module, but
contract tests will assert that its tier/cadence/amount matches a safe public
billing catalog response. Provider plan ids and credentials are never public.

### 3.2 Guarded plan provisioning

Add an operator command with these modes (exact CLI spelling may follow repository
conventions during implementation):

```text
billing plans verify  --environment test|live
billing plans create  --environment test
billing plans create  --environment live --confirm-live <catalog-version>
```

The command will:

1. load the environment-specific Razorpay credentials from secret settings;
2. calculate a stable fingerprint of safe catalog properties;
3. fetch and verify an existing configured plan id when present;
4. print the proposed Razorpay payload with credentials redacted;
5. create only with an explicit `create` operation (no creation on app startup);
6. never automatically retry an ambiguous plan-creation timeout;
7. print the resulting non-secret plan id for the operator to install in the
   environment configuration; and
8. write no key, secret, raw response, customer data, or webhook payload to logs.

Razorpay's Plan API does not provide a general application idempotency contract in
the cited plan-creation documentation. Therefore plan creation is an explicit
one-shot operator action. A duplicate created during an ambiguous network result
must be resolved in the Razorpay Dashboard; application traffic never creates
plans.

### 3.3 Subscription creation safety

- `POST /api/v1/billing/checkout` accepts only `{tier_key:"paid", cadence:"monthly"}`
  plus an `Idempotency-Key` header. It accepts no amount, currency, provider, plan
  id, country, or return URL.
- The server inserts a `BillingCheckoutAttempt` before provider I/O and includes
  only the opaque attempt UUID/billing-account UUID in Razorpay `notes`.
- A completed attempt returns the validated HTTPS Razorpay `short_url`.
- An ambiguous provider timeout is not blindly retried. Reconciliation searches
  bounded recent provider objects by the opaque attempt note before allowing a new
  mutation.
- A billing account with a live/pending subscription cannot create another one.
- The server chooses INR versus USD from the persisted billing profile. A browser
  cannot submit currency, country, exchange rate, tax, or provider.
- Provider redirects set the UI to “Confirming payment”; they never upgrade the
  account.

## 4. Backend implementation

### Phase A — persistence and atomic bootstrap

Implement the V6 billing models in `models/billing.py`:

- `BillingAccount` (one per owner user);
- `WorkspaceBillingLink` (one sponsor per workspace);
- `BillingCustomer` (provider identity, never in public DTOs);
- `BillingSubscription` (history plus one-current-subscription partial unique
  index);
- `AccountEntitlement` (one locked current projection);
- `BillingCheckoutAttempt`; and
- `BillingWebhookEvent` (safe summary and SHA-256 only, never raw payload).

Import them in `models/__init__.py`; the greenfield `0001_initial` metadata-based
migration picks them up. Registration creates User + personal Workspace + owner
membership + BillingAccount + Free entitlement + WorkspaceBillingLink in one
transaction. Owner-created workspaces link to the same billing account. An
idempotent backfill command repairs existing users/workspaces and is safe under
concurrency.

### Phase B — entitlement resolution and enforcement

Create `domain/entitlements` as the only commercial capability resolver:

- owner billing summary resolves by authenticated user;
- workspace capability resolves only after `require_workspace_member` and through
  `WorkspaceBillingLink`;
- invited users inherit the active workspace sponsor's entitlement;
- missing/corrupt sponsorship fails closed;
- entitlement changes lock `AccountEntitlement FOR UPDATE`, increment the monotonic
  revision, and synchronize every sponsored workspace's Site Health projection via
  the existing `set_entitlement()` service in the same transaction;
- new audit configuration freezes tier/revision/capabilities while completed
  evidence remains immutable after downgrade.

The first billing release must enforce the capability server-side at every new
paid-work entry point it exposes. UI gating is explanatory only.

### Phase C — Razorpay adapter

Add `connectors/billing` with neutral DTOs/errors, a `BillingProvider` protocol,
factory, safe shared HTTP client, fake provider, and
`RazorpayBillingProvider`. The adapter owns translation only:

- Basic-auth API calls use secrets from settings;
- bounded timeouts and safe error codes are config-owned;
- hosted authorization URLs are HTTPS and host-allow-listed;
- cancellation maps to Razorpay end-of-cycle cancellation when requested;
- no request/response body, authorization header, signature, or customer PII is
  logged; and
- raw webhook verification happens before JSON parsing or persistence.

There is no fake Razorpay customer portal. `/billing/manage` returns only actions
the provider actually supports; authorization/recovery links may be exposed when
valid, while cancellation remains a first-party CiteLadder action.

### Phase D — webhook-owned lifecycle

Implement `/api/v1/billing/webhooks/razorpay` outside auth, with config-owned rate
limits and body-size bounds:

1. read the raw request bytes once;
2. validate `X-Razorpay-Signature` with HMAC SHA-256 and constant-time comparison;
3. validate and dedupe `X-Razorpay-Event-Id`;
4. allow-list event type and bounded fields before parsing into a neutral event;
5. persist event identity, lock the subscription + entitlement, reject stale
   state, and apply the projection atomically;
6. store only a safe summary plus raw-body SHA-256; and
7. acknowledge duplicates with 2xx, return 400 for invalid signatures, 5xx only
   for retryable verified-event failures.

Initial state mapping:

| Razorpay state/event | Internal state | Access |
|---|---|---|
| `created`, `authenticated` | `pending` | Free; authentication alone does not prove paid service |
| `active`, successful `charged` | `active` | Paid |
| `pending` | `past_due` | Paid through configured grace, then Free |
| `halted` | `unpaid` | Free after grace policy |
| end-of-cycle cancellation requested | `cancel_scheduled` | Paid through period end |
| `cancelled` | `cancelled` | Paid only while a verified paid-through time is future |
| `completed`, `expired` | `expired` | Free |

Webhook events may be reordered, so event arrival time alone is not sufficient.
Use provider timestamps/state version where available; for ambiguous transitions,
fetch the current subscription server-side and feed it through the same projection
function. Add a bounded reconciliation command for verified but failed events and
provider/database disagreement.

### Phase E — billing APIs

Implement the V6 routes with strict DTOs and stable error codes:

- `GET /billing/catalog` — safe public Free/Paid/Enterprise display contract;
- `GET /billing/me` — authenticated owner's safe billing summary;
- `POST /billing/checkout` — owner-only, server-selected Razorpay plan;
- `POST /billing/manage` — provider-supported actions only;
- `POST /billing/cancel` — owner-only, idempotent end-of-cycle cancellation;
- `GET /workspaces/{workspace_id}/entitlements` — membership-authorized effective
  capabilities; and
- `POST /billing/webhooks/razorpay` — signature-authorized transport endpoint.

No normal DTO includes provider customer ids, subscription ids, plan ids, billing
address, API keys, webhook secrets, or raw event data.

## 5. Frontend implementation

### 5.1 Authenticated billing experience

- Add strict Zod billing/catalog/entitlement schemas and query keys.
- Add `EntitlementProvider` inside `SessionGuard` and `ProjectProvider`.
- Add Settings → Billing with Free/Paid status, renewal/end date, pending/grace
  explanations, Upgrade, retry/manage when genuinely supported, and Cancel.
- Navigate checkout in the top window to the server-returned Razorpay hosted URL.
- Add a same-origin return route that displays “Confirming payment” and refetches
  billing/entitlements until webhook-confirmed or a bounded timeout; no optimistic
  Paid state.
- Preserve the last successful entitlement on transient failures, but fail closed
  for new paid-only actions when none has loaded.

### 5.2 Pricing contract

Replace the unsupported four self-serve tiers with:

- Free;
- Paid monthly (the existing Starter-level capability surface); and
- a visually separate Enterprise sales card/CTA that is not represented as a
  self-serve Razorpay plan.

Do not advertise a trial, annual discount, INR amount, GST inclusion, Pro-only
limits, or payment method until the corresponding owner decision/account
capability is verified. Tests compare pricing copy with `/billing/catalog` safe
values.

### 5.3 Stable enterprise demo funnel

- Change the centralized `DEMO_HREF` from `/enterprise#contact` to `/demo`.
- Add a server-rendered `/demo` marketing route with clear expectations, privacy
  copy, sales contact, and a “Schedule demo” action using an owner-supplied HTTPS
  booking URL.
- If the booking URL is absent, render an honest “Email sales” fallback using the
  configured public sales address; never render a broken or fake booking action.
- Update Enterprise hero/contact CTAs, pricing Enterprise CTA, landing final CTA,
  solutions, comparison, navigation, and footer through the centralized constant.
- Keep `/enterprise#contact` valid as explanatory content, but its action points to
  `/demo`.
- Do not embed a third-party scheduler or collect lead PII in CiteLadder until its
  privacy/cookie behavior and data-processing terms are approved. A plain external
  booking link is the launch default.

## 6. Security and failure model

- Razorpay keys and webhook secrets exist only in deployment secret storage.
- Test and live keys, plan ids, webhook secrets, and endpoints are separate.
- No secret is pasted into chat, committed, returned, or logged.
- Checkout mutation is owner-only; workspace membership never confers billing
  ownership.
- Webhook auth is signature-only over raw bytes; session auth does not apply.
- Bounded request bodies, field lengths, event summaries, HTTP timeouts, retries,
  and rate limits are config-owned.
- Provider API reads may retry safely; ambiguous writes reconcile before retry.
- A provider outage never upgrades entitlement. Existing verified Paid access
  follows the configured paid-through/grace policy.
- Downgrade/cancellation never mutates completed audits, crawls, metrics, or raw
  evidence.
- A kill switch disables new checkout without affecting webhook processing or
  existing entitlement reads.

## 7. Verification matrix

Backend focused coverage:

- registration/backfill atomicity and concurrent uniqueness;
- personal, agency-owner, and invited-member entitlement resolution;
- one current subscription and one workspace sponsor constraints;
- catalog validation and plan-payload snapshots;
- provisioning dry-run, test create, configured-plan drift, redaction, and
  ambiguous timeout;
- checkout ownership, idempotency, duplicate live subscription, injection
  rejection, and safe URL validation;
- valid/invalid Razorpay signatures over exact raw bytes;
- duplicate and out-of-order events, late activation, checkout/webhook race,
  pending/grace/halted/cancel/completed transitions, replay/reconciliation;
- secrets/external ids/PII absent from DTOs and logs; and
- Site Health/audit downgrade blocks new work while preserving history.

Frontend focused coverage:

- strict billing schemas and same-origin URLs;
- Free bootstrap, workspace switching, invited agency entitlement;
- pending → webhook-confirmed Paid, grace, downgrade, 401, transient 5xx;
- pricing/catalog agreement and no unapproved claims;
- every demo CTA resolves to centralized `/demo`;
- `/demo` booking and missing-config email fallback; and
- keyboard/focus/accessibility behavior for Settings Billing and checkout status.

Operational acceptance:

1. run all focused backend/frontend tests, lint, build, and `alembic upgrade head`;
2. create and verify the Razorpay **test** plan;
3. complete an INR test lifecycle: create → authorize → active/charged → pending
   or failed simulation → recover/halt → end-of-cycle cancel;
4. replay duplicates and reordered webhook fixtures;
5. verify no provider object is created by browser refresh or application startup;
6. confirm `/demo` from every public CTA and the configured booking destination;
7. create and verify the **live** plan only after KYC, policy, tax, method, webhook,
   and settlement gates pass;
8. enable checkout for an allow-list, reconcile Razorpay Dashboard against the DB,
   then widen rollout; and
9. keep the checkout kill switch and webhook processing independently operable.

## 8. Rollout and rollback

1. Ship persistence, Free bootstrap, read-only entitlement API/UI, and demo route.
2. Backfill existing accounts as Free and verify sponsor integrity.
3. Deploy webhook endpoint and reconciliation tooling with checkout disabled.
4. Register/test the webhook and provision the Razorpay test plan.
5. Complete sandbox lifecycle and security tests.
6. Provision live plan and live webhook after owner checklist sign-off.
7. Enable checkout to staff/allow-list accounts, then India generally.

Rollback disables **new checkout only**. Continue receiving webhooks and serving
verified entitlement state. Never delete provider history, billing history, or
product evidence to roll back an integration release.

## 9. Explicit non-goals

- Stripe, automatic cross-provider migration, usage/seat billing, coupons,
  overages, custom card/UPI forms, or CiteLadder-funded model usage.
- Self-serve Enterprise checkout or automatic Enterprise entitlement grants.
- Annual Paid until an exact annual catalog is approved.
- A first-party lead database, CRM, scheduler embed, or marketing-email workflow;
  `/demo` links to an approved external booking destination at launch.
- Tax/legal conclusions. Product and accounting owners approve price/GST/invoice
  behavior before live creation.

## 10. Primary sources checked

- [Razorpay Subscriptions overview](https://razorpay.com/docs/payments/subscriptions/)
- [Razorpay Subscriptions integration guide](https://razorpay.com/docs/payments/subscriptions/integration-guide/)
- [Razorpay Create a Plan API](https://razorpay.com/docs/api/payments/subscriptions/create-plan/)
- [Razorpay Create a Subscription API](https://razorpay.com/docs/api/payments/subscriptions/create-subscription/)
- [Razorpay subscription states](https://razorpay.com/docs/payments/subscriptions/states/)
- [Razorpay supported subscription payment methods](https://razorpay.com/docs/payments/subscriptions/supported-payment-methods/)
- [Razorpay payment retries](https://razorpay.com/docs/payments/subscriptions/payment-retries/)
- [Razorpay subscription webhook events](https://razorpay.com/docs/webhooks/payloads/subscriptions/)
- [Razorpay webhook validation/testing](https://razorpay.com/docs/webhooks/validate-test/)
- [Razorpay webhook best practices](https://razorpay.com/docs/webhooks/best-practices/)
- [Razorpay KYC documents by business type](https://razorpay.com/docs/payments/business-types-kyc-documents/)
- [Razorpay account activation details](https://razorpay.com/docs/payments/dashboard/account-settings/activation-details/)

Provider behavior, pricing, regulations, and enabled payment methods can change;
recheck these sources immediately before live provisioning.
