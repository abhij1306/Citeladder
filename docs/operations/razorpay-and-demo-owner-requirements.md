# Owner requirements — Razorpay billing and enterprise demos

> Complete this checklist before CiteLadder enables production checkout. Never
> paste API key secrets or webhook secrets into this file, Git, an issue, or chat.
> Store secrets directly in the deployment secret manager and mark only the
> non-secret completion status here.

Companion implementation plan:
[`../plans/v6-razorpay-production-and-enterprise-demo.md`](../plans/v6-razorpay-production-and-enterprise-demo.md).

## 1. Blocking commercial decisions

Record the approved values in a dated decision record (amounts are examples of
fields, not suggested values):

```text
Catalog version:
Effective date:
Free display name:
Paid display name:
Paid monthly USD amount: $49 (approved implementation anchor)
USD/INR provisioning rate and source/date:
Derived Paid monthly INR base amount (minor units):
GST is displayed and charged extra for India: yes (approved direction)
GST rate/treatment approved by:
Trial enabled? yes/no; if yes, exact duration and first-charge behavior:
Past-due grace duration:
Cancellation: end of period or immediate:
Refund policy and entitlement effect:
Monthly subscription cycle bound (recommended product policy, not a guess):
Annual plan at launch? no/yes; if yes, exact amount and policy:
Customer communications handled by Razorpay? yes/no:
```

Why this is a live-plan gate: Razorpay requires a concrete amount and currency.
CiteLadder will derive the India price once from the operator-supplied USD/INR rate,
add the configured GST, and freeze the result into the plan. It will not reprice an
active recurring mandate from a live exchange rate. Non-India launch checkout is
USD; a cardholder's issuer may convert that charge into the card account currency.

## 2. Legal, tax, invoice, and policy inputs

Obtain India-qualified accounting/legal review and provide the approved outcome:

- [ ] Legal entity/business type and registered legal name.
- [ ] Business PAN and GST registration/GSTIN treatment.
- [ ] Registered business and billing address, state/place-of-supply handling.
- [ ] Bank account in the legal entity's name and settlement details.
- [ ] Whether consumer-facing prices include GST and the exact invoice wording.
- [ ] Domestic SaaS invoicing treatment.
- [ ] Export-of-services/LUT/IGST/FIRC or equivalent evidence policy if
      international sales will later be enabled.
- [ ] Public Terms of Service URL.
- [ ] Public Privacy Policy URL.
- [ ] Public Refund and Cancellation Policy URL.
- [ ] Public customer-support email and, if required, phone/address.
- [ ] Recurring-payment consent and cancellation copy.
- [ ] Data retention and deletion policy for billing records.

This document is an engineering checklist, not tax or legal advice.

The legal entity, PAN/GSTIN, settlement bank, registered address, and merchant
support details belong in Razorpay's merchant onboarding/Dashboard and the
approved legal documents. They are intentionally not hard-coded into CiteLadder
or collected in its checkout API. The application currently stores only the
customer account's two-letter billing country. Provider-confirmed country/tax
reconciliation remains a live-launch gate: until sandbox evidence proves that
the selected INR/USD route matches Razorpay payment/invoice evidence, keep
`BILLING_RAZORPAY_LIVE_READY=false` and `BILLING_CHECKOUT_ENABLED=false`.

## 3. Razorpay account readiness

- [ ] Create the Razorpay account for the approved legal entity.
- [ ] Complete sign-up and KYC. Razorpay's Dashboard must show the account as
      **Activated**, not merely test-enabled.
- [ ] Confirm Razorpay Subscriptions is enabled for the live account.
- [ ] Confirm the live account's approved methods: Cards, UPI AutoPay, and/or
      eMandate. Do not rely on generic documentation; record what Razorpay enabled
      for this merchant category.
- [ ] Confirm mandate amount limits cover the approved Paid price.
- [ ] Confirm settlement schedule, fees, refunds, disputes, and reserve terms.
- [ ] Configure the customer-facing business name, logo, support details, and
      invoice settings in Razorpay.
- [ ] Confirm whether Razorpay or CiteLadder sends customer subscription
      notifications.
- [ ] Name at least two Razorpay Dashboard users and enable strong MFA/access
      controls; avoid a shared owner login.

## 4. Secrets and non-secret identifiers

Each deployment reads the following exact settings. Install test values only in
staging and live values only in production; the names stay the same because the
deployment boundary provides the separation.

Secret values — install directly in the deployment secret manager:

```text
BILLING_RAZORPAY_KEY_SECRET
BILLING_RAZORPAY_WEBHOOK_SECRET
```

Non-secret but environment-specific values:

```text
BILLING_RAZORPAY_KEY_ID
BILLING_RAZORPAY_PAID_MONTHLY_USD_PLAN_ID
BILLING_RAZORPAY_PAID_MONTHLY_INR_PLAN_ID
BILLING_CATALOG_VERSION
BILLING_USD_INR_RATE
BILLING_INDIA_GST_RATE=0.18
BILLING_CHECKOUT_ENABLED=false        # stays false until go-live sign-off
BILLING_RAZORPAY_LIVE_READY=false     # stays false until live lifecycle passes
BILLING_RAZORPAY_INTERNATIONAL_READY=false
BILLING_SUBSCRIPTION_TOTAL_CYCLES=1200
BILLING_PAST_DUE_GRACE_DAYS=3
```

Rules:

- Never reuse test keys, live keys, or webhook secrets across environments.
- The Razorpay API key secret is not the webhook secret.
- Never send a secret to the browser or place it in a `NEXT_PUBLIC_*` variable.
- Rotate a suspected secret immediately. During webhook-secret rotation, account
  for retries signed with the previous secret as Razorpay documents.
- Plan ids are not credentials, but still belong in environment configuration so
  test/live cannot be crossed accidentally.

## 5. Production URLs and webhook setup

Provide:

```text
Canonical production frontend origin:
Canonical production backend origin (server-only):
Checkout return route/origin:
Razorpay live webhook URL:
Razorpay test/staging webhook URL:
Webhook alert email:
Operations incident email/channel:
```

The expected public webhook path is:

```text
https://<backend-public-origin>/api/v1/billing/webhooks/razorpay
```

Subscribe only to the implemented subscription allow-list:

```text
subscription.authenticated
subscription.activated
subscription.charged
subscription.pending
subscription.halted
subscription.cancelled
subscription.completed
subscription.expired
subscription.paused
subscription.resumed
```

The endpoint verifies every signature over the exact raw body before dispatch. A validly
signed event outside this allow-list is acknowledged with `204` and does not mutate billing
state. An allow-listed event for an unknown external subscription is recorded as `unmatched`,
acknowledged with `204`, and does not mutate entitlements. Duplicate event ids and stale
provider-state versions are also acknowledged idempotently. Malformed payloads and invalid
signatures remain non-2xx so they are visible as configuration or delivery failures.

The webhook URL must use modern HTTPS/TLS and remain reachable independently of
the frontend deployment. Add monitoring for invalid signatures, non-2xx delivery,
duplicate/reordered events, reconciliation drift, and webhook deactivation.

## 6. Razorpay plan creation procedure

Run these commands from `backend/`:

```text
uv run python -m scripts.provision_razorpay_plans propose --environment test
uv run python -m scripts.provision_razorpay_plans verify --environment test
uv run python -m scripts.provision_razorpay_plans create --environment test
uv run python -m scripts.provision_razorpay_plans create --environment live --confirm-live billing-v1
```

`verify` and `create` reject credentials whose Razorpay key prefix does not match the selected
environment (`rzp_test_…` for test, `rzp_live_…` for live). `propose` performs no provider I/O.

1. Install test credentials in staging.
2. Run catalog validation and a redacted dry-run.
3. Create the test Paid-monthly plan once.
4. install the returned test plan id in staging configuration.
5. run `verify` and confirm period, interval, currency, amount, and item name.
6. complete the full sandbox lifecycle and webhook replay suite.
7. complete KYC, policy, payment-method, settlement, and live webhook gates.
8. install live credentials with checkout/live-ready flags still false.
9. run the redacted live dry-run and obtain a second-person review.
10. create the live plan with the explicit catalog-version confirmation.
11. install and verify the live plan id.
12. execute one real low-risk authorized lifecycle and reconcile Dashboard,
    database, invoice, settlement, and cancellation behavior.
13. enable the live-ready flag, then checkout for an allow-list only.

Creating or editing a Razorpay plan manually in the Dashboard outside this process
risks catalog drift. If it happens, record the plan id and run verification before
using it.

## 7. Enterprise demo funnel inputs

Provide the launch destination and public contact details:

```text
Public sales email:
Approved HTTPS booking URL (Cal.com, Calendly, or other approved provider):
Booking provider/vendor:
Demo duration:
Availability owner/time zone:
Expected response-time copy:
Privacy Policy URL covering the booking vendor:
Cookie/consent requirement for this vendor:
Optional analytics allowed on /demo? yes/no and approved tool:
```

Install the approved values only on the Next.js server (never as
`NEXT_PUBLIC_*`):

```text
DEMO_BOOKING_URL=https://<approved-provider>/...
PUBLIC_SALES_EMAIL=sales@<approved-domain>
```

Launch behavior:

- CiteLadder owns a stable public `/demo` route.
- Every public “Book a demo”/Enterprise sales CTA points to `/demo` through the
  centralized `DEMO_HREF`.
- `/demo` opens the approved external HTTPS booking destination.
- Without a booking URL, `/demo` truthfully offers `mailto:<public-sales-email>`;
  it does not show a fake scheduler.
- CiteLadder does not persist demo-lead PII in the first release. If a first-party
  form/CRM is desired later, approve its fields, lawful basis/consent, retention,
  deletion, anti-spam controls, notification provider, and processor agreement in
  a separate change.

## 8. Required sandbox acceptance evidence

Attach or record non-secret evidence for:

- [ ] Provisioned test plan verified against the approved catalog.
- [ ] Subscription authorization through hosted Razorpay checkout.
- [ ] Initial payment produces webhook-confirmed Paid; redirect alone does not.
- [ ] Duplicate event is acknowledged without duplicate mutation.
- [ ] Reordered event does not downgrade/upgrade incorrectly.
- [ ] Failed renewal enters grace, then recovers or downgrades as approved.
- [ ] Halted subscription fails closed for new Paid work.
- [ ] End-of-period cancellation preserves access only through verified paid time.
- [ ] Completed/expired subscription resolves Free.
- [ ] Invited user sees the active workspace sponsor's entitlement.
- [ ] Existing audit/site evidence remains readable after downgrade.
- [ ] No secret, external customer id, full webhook payload, or billing PII appears
      in API responses or logs.
- [ ] Checkout kill switch blocks new checkout but webhooks still process.
- [ ] Every demo CTA reaches `/demo`, and `/demo` reaches the approved booking URL
      or honest email fallback.

## 9. Live go/no-go sign-off

Record names and dates; no secrets:

```text
Product/catalog approval:
Accounting/tax approval:
Legal/policy approval:
Security review:
Engineering verification:
Razorpay account/KYC verified by:
Live payment + invoice + settlement verified by:
Support/refund owner:
Incident owner:
Allow-list launch date:
General India launch approval/date:
```

If any required approval, live lifecycle, webhook monitoring, or rollback control
is missing, the correct state is `BILLING_CHECKOUT_ENABLED=false`.

## 10. India-first alternatives retained as contingency

Razorpay is the selected launch provider, but the provider boundary should remain
neutral. Current alternatives worth a sandbox evaluation if Razorpay activation,
methods, or commercials fail are:

1. **Cashfree Subscriptions** — its current documentation exposes subscription
   status/auth/payment/refund webhooks and hosted/custom checkout surfaces.
2. **PayU recurring payments / Zion** — its current documentation covers plans,
   subscriptions, cards, UPI consent/mandates, pre-debit notifications, recurring
   transactions, cancellation, and lifecycle webhooks.
3. **PhonePe PG AutoPay** — its current developer documentation exposes AutoPay
   subscription setup, authorization, redemption, status, pause/unpause, revoke,
   and cancel APIs. It would require a separate adapter and commercial/onboarding
   evaluation.

Primary sources:

- [Cashfree subscription webhook events](https://www.cashfree.com/docs/payments/subscription/webhooks)
- [PayU recurring payments overview](https://docs.payu.in/docs/introduction-recurring-payments-integration.md)
- [PayU plans/subscription automation](https://docs.payu.in/docs/understanding-plan.md)
- [PhonePe PG AutoPay introduction](https://developer.phonepe.com/payment-gateway/autopay/api-integration/introduction)

Do not switch a live customer between providers silently. A migration remains an
explicit cancel/re-subscribe operation with owner approval.
