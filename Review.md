# CiteLadder Code Review Guidelines & Agent Reference (`Review.md`)

This document serves as the authoritative code review reference for **AI Code Reviewing Agents** and human reviewers operating on the **CiteLadder** repository (`abhij1306/CiteLadder`).

It is synthesized directly from historical Pull Request reviews, automated CodeRabbit findings, CodeQL security alerts, project invariants, and developer review feedback across all Pull Requests (PR #1 through PR #33).

---

## ⛔ CRITICAL ZERO-TOLERANCE INVARIANT: Configuration Must NOT Live in Code

**Rule 0 / Invariant 1:** Externally tunable operational configuration—model names, scoring thresholds, timeouts, rate limits, page sizes, retry counts, API endpoints, feature flags, and guardrail knobs—MUST NEVER be hardcoded inline inside service, domain, worker, analysis, API, or UI component code. Fixed validation rules and structural values that define a local contract (for example, form field length bounds, enum cardinality, grid spans, or RFC-mandated constants) are not operational configuration and may remain beside the schema or component they govern.

* **Backend Rule:** All config values MUST be declared in and loaded from `backend/app/core/config/*` (e.g., `config/__init__.py` `Settings`, `config/provider_catalog.py`, `config/billing.py`, `config/site_health.py`). Service and worker code reads settings objects injected or imported from `app.core.config`.
* **Frontend Rule:** All environment variables, feature flags, API base paths, and tunable UI thresholds MUST live in `process.env`, `lib/config/*`, or the API-contract layer. Components and hooks must NEVER hardcode API endpoints or magic limits.
* **Review Action:** Code reviewing agents MUST **REJECT** diffs that introduce tunable operational configuration or model/endpoint strings into business or presentation logic. Do not flag self-explanatory static validation bounds or structural constants merely because they are numeric; require centralization only when changing the value is an operational tuning decision.

---

## 📋 Code Review Checklist for Agents

When reviewing any Pull Request or code change in `CiteLadder`, agents MUST systematically verify the code against these critical categories:

- [ ] **0. Zero Config-in-Code**: Are all model IDs, timeouts, limits, thresholds, and endpoints loaded strictly from `app/core/config/*` or `process.env`?
- [ ] **1. Security & Network Boundary**: Are base URLs, webhooks, and provider endpoints validated for HTTP/HTTPS scheme and SSRF safety?
- [ ] **2. Database & Concurrency**: Are bulk inserts batched? Are `IntegrityError` exceptions mapped to specific constraint failures rather than blanket 404s/409s?
- [ ] **3. Schema & Input Validation**: Are Pydantic string fields validated *before* post-processing/trimming? Are request headers length-bounded?
- [ ] **4. Frontend & Next.js State**: Is mutation state (e.g. `isPending`, `crawlStarting`) scoped to the active project/workspace ID? Does layout CSS contaminate global scope?
- [ ] **5. External Integrations (Billing & LLMs)**: Do webhooks handle domain exceptions without uncaught 500s? Are external API metric numbers safely coerced without throwing `ValueError`?
- [ ] **6. Resilience & Cleanup**: Are advisory locks safely hashed with 64-bit namespace keys? Are cache TTL expiration timestamps strictly enforced?

---

## 🗂️ Detailed Categories & Recurring Anti-Patterns

### 0. Configuration Management & Config-in-Code Violations

#### 🚨 Anti-Pattern: Hardcoding Model Names, Timeouts, or Thresholds in Logic
Hardcoding values such as model identifiers (`"gpt-5.4"`), timeout seconds (`30`), batch limits (`100`), or score thresholds inside domain, service, worker, or UI code makes parameters untunable and breaks environment isolation.

* **Incorrect (Backend):**
  ```python
  # BAD: Hardcoded model name, timeout, and max retry in service/connector code
  async def call_provider(prompt: str):
      client = httpx.AsyncClient(timeout=30.0)  # Hardcoded timeout!
      response = await client.post(
          "https://api.openai.com/v1/chat/completions",  # Hardcoded endpoint!
          json={
              "model": "gpt-5.4",
              "messages": [{"role": "user", "content": prompt}],
          },  # Hardcoded model!
      )
  ```
* **Correct (Backend):**
  ```python
  # GOOD: Reading from app/core/config/
  from app.core.config import settings
  from app.core.config.provider_catalog import ACTIVE_TRANSPORTS


  async def call_provider(prompt: str):
      route = ACTIVE_TRANSPORTS["openai"]
      client = httpx.AsyncClient(timeout=settings.PROVIDER_TIMEOUT_SECONDS)
      response = await client.post(
          f"{settings.OPENAI_BASE_URL}/v1/chat/completions",
          json={
              "model": route.transport_model,
              "messages": [{"role": "user", "content": prompt}],
          },
      )
  ```

* **Incorrect (Frontend):**
  ```tsx
  // BAD: Hardcoded API endpoint URL and page size in React component
  const fetchItems = () => fetch("http://localhost:8000/api/v1/projects?limit=50");
  ```
* **Correct (Frontend):**
  ```tsx
  // GOOD: Using relative same-origin proxy base and central config
  import { DEFAULT_PAGE_SIZE } from "@/lib/config/constants";
  import { apiClient } from "@/lib/api/client";

  const fetchItems = () => apiClient.get(`/projects`, { params: { limit: DEFAULT_PAGE_SIZE } });
  ```

---

### 1. Security, Network Boundaries & SSRF

#### 🚨 Recurring Anti-Pattern: Unvalidated Outbound URLs (SSRF)
Accepting `base_url`, `provider_endpoint`, or logo/favicon URLs as arbitrary strings and making outbound HTTP requests allows Server-Side Request Forgery (SSRF) and plaintext credential leakage over `http`.

* **Incorrect:**
  ```python
  # BAD: Accepting unconstrained URL and sending bearer token directly
  client = httpx.AsyncClient(base_url=provider.base_url)
  response = await client.post(
      "/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}
  )
  ```
* **Correct:**
  ```python
  # GOOD: Validating URL scheme, host, and disallowing unsafe protocols
  from pydantic import HttpUrl, AnyHttpUrl


  def validate_provider_url(url_str: str) -> str:
      parsed = urllib.parse.urlparse(url_str)
      if parsed.scheme not in ("http", "https"):
          raise ValueError("URL scheme must be http or https")
      if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1"):
          raise ValueError("Plaintext HTTP is allowed only for local loopback")
      return url_str
  ```

#### 🚨 Recurring Anti-Pattern: Advisory Lock Key Truncation
Truncating UUIDs or string IDs (e.g., `uuid[:4]` or `int(uuid[:8], 16)`) to fit into PostgreSQL advisory locks causes lock key collisions across unrelated projects or prompt sets.

* **Incorrect:**
  ```python
  # BAD: First 4 bytes collide easily across UUIDs
  lock_id = int(str(project_id).replace("-", "")[:8], 16)
  ```
* **Correct:**
  ```python
  # GOOD: Stable 64-bit BLAKE2b hash with namespace
  import hashlib


  def get_advisory_lock_key(namespace: str, resource_id: str) -> int:
      digest = hashlib.blake2b(
          f"{namespace}:{resource_id}".encode(), digest_size=8
      ).digest()
      return int.from_bytes(digest, byteorder="big", signed=True)
  ```

#### 🚨 Recurring Anti-Pattern: OS-Specific Path Separators in Baseline Files
Storing Windows backslash (`\`) paths in security baseline files (e.g., `.secrets.baseline`) causes secret scanners to fail or ignore rules in Linux CI environments. Always use forward slashes (`/`).

---

### 2. Database Integrity, Concurrency & Exception Mapping

#### 🚨 Recurring Anti-Pattern: Catch-All `IntegrityError` to 404 or 409
Catching generic `IntegrityError` and assuming it was caused by a specific duplicate record or missing item misreports foreign-key violations, check constraint failures, or database connectivity glitches as false HTTP 404s or 409s.

* **Incorrect:**
  ```python
  # BAD: Any DB integrity error returned as 404
  try:
      db.commit()
  except IntegrityError:
      db.rollback()
      raise PromptSetNotFoundError("Prompt set deleted")  # Misleading!
  ```
* **Correct:**
  ```python
  # GOOD: Re-verify target existence or inspect constraint name
  try:
      db.commit()
  except IntegrityError as exc:
      db.rollback()
      # Explicit scope check after rollback
      if not db.query(PromptSet).filter_by(id=set_id).first():
          raise PromptSetNotFoundError("Prompt set was deleted")
      raise
  ```

#### 🚨 Recurring Anti-Pattern: N+1 DB Queries in Bulk Imports
Executing single-row `INSERT` or `UPDATE` queries inside a loop during CSV or JSON imports (e.g., product catalog or prompt imports) creates hundreds of avoidable DB round-trips.

* **Incorrect:**
  ```python
  # BAD: One DB query per CSV row
  for row in csv_rows:
      db.add(Product(name=row["name"], sku=row["sku"]))
      db.flush()
  ```
* **Correct:**
  ```python
  # GOOD: Bulk insert in batched chunks
  products = [Product(name=r["name"], sku=r["sku"]) for r in csv_rows]
  db.bulk_save_objects(products)
  db.commit()
  ```

#### 🚨 Recurring Anti-Pattern: Foreign Key `ON DELETE SET NULL` Side Effects
Using `ON DELETE SET NULL` on audit or metric snapshot foreign keys (`product_id`, `competitor_id`) without keeping an immutable fallback `entry_id` / `frozen_catalog_id`. When catalog entries are deleted, snapshots become orphaned and fail unique constraints.

---

### 3. Validation, Schemas & Type Safety (FastAPI & Pydantic)

#### 🚨 Recurring Anti-Pattern: Post-Validation Mutation / Trim
Trimming string fields inside service methods *after* Pydantic validation allows whitespace-only strings (e.g. `"   "`) to pass schema validation and become empty strings (`""`) in the database.

* **Incorrect:**
  ```python
  # BAD: Schema allowed whitespace, service converted it to invalid empty string
  def create_topic(payload: TopicCreate):
      clean_name = payload.name.strip()  # Might become ""!
      db.add(Topic(name=clean_name))
  ```
* **Correct:**
  ```python
  # GOOD: Validate and trim at the Pydantic schema boundary
  class TopicCreate(BaseModel):
      name: str

      @field_validator("name")
      @classmethod
      def validate_non_empty(cls, v: str) -> str:
          v_stripped = v.strip()
          if not v_stripped:
              raise ValueError("Topic name cannot be empty or whitespace-only")
          return v_stripped
  ```

#### 🚨 Recurring Anti-Pattern: Unbounded Input Headers & Query Parameters
Accepting custom headers (such as `Idempotency-Key`) or query parameters without character length bounds causes DB `DataError` exceptions when writing to bounded database columns (e.g., `VARCHAR(128)`).

* **Incorrect:**
  ```python
  # BAD: Header string length is unbounded
  idempotency_key: str | None = Header(None)
  ```
* **Correct:**
  ```python
  # GOOD: Bound header length with Header/Field constraints
  idempotency_key: str | None = Header(None, max_length=128)
  ```

#### 🚨 Recurring Anti-Pattern: Swallowing Corrupted Import Data with `errors="replace"`
Using `bytes.decode("utf-8", errors="replace")` on uploaded CSV files silently converts malformed characters into the Unicode replacement character (U+FFFD), corrupting SKUs and names. Fail fast with an HTTP 422 error on decoding issues instead.

---

### 4. Frontend State, Next.js & UI Architecture

#### 🚨 Recurring Anti-Pattern: Unscoped Mutation State Across Workspace/Project Switches
Deriving UI flags (e.g., `crawlStarting`, `isPending`) from TanStack Query mutations without verifying that the mutation variables match the currently active project or workspace ID.

* **Incorrect:**
  ```tsx
  // BAD: Mutation success flag persists after user switches projects
  const crawlStarting = createMutation.isSuccess;
  ```
* **Correct:**
  ```tsx
  // GOOD: Guard mutation state with active project ID
  const crawlStarting = createMutation.isSuccess && createMutation.variables?.projectId === activeProjectId;
  ```

#### 🚨 Recurring Anti-Pattern: Route-Owned Global CSS
Defining unscoped global styles in nested route layouts creates order-dependent
visual state during client-side navigation. CiteLadder is light-only: global
tokens and base styles belong exclusively to `frontend/app/globals.css`, and
routes consume those semantic tokens without mutating the document root.

#### 🚨 Recurring Anti-Pattern: Duplicate `<h1>` Heading Tags
Rendering an `<h1>` tag in shared app shells (`PageHeader`) as well as in specific nested pages (`UrlDetail`, `Dashboard`). Accessibility and SEO require exactly one `<h1>` per page.

---

### 5. External Integrations (Razorpay, Shopify, LLM Providers)

#### 🚨 Recurring Anti-Pattern: Narrow Webhook Exception Handling
Catching only generic `InvalidWebhookError` in webhook endpoint handlers while domain logic raises specific exceptions like `BillingConflictError` or `WorkspaceNotFoundError`. This causes valid webhook calls to crash with uncaught HTTP 500 errors.

* **Incorrect:**
  ```python
  # BAD: Missing handling for domain exceptions raised by webhooks
  @router.post("/webhooks/razorpay")
  async def razorpay_webhook(request: Request):
      try:
          return await process_webhook(request)
      except InvalidWebhookError:
          return JSONResponse(status_code=400, content={"detail": "Invalid signature"})
      # Uncaught BillingConflictError returns 500!
  ```
* **Correct:**
  ```python
  # GOOD: Handle domain conflicts explicitly with 200 or 409 response
  except BillingConflictError as e:
      logger.warning(f"Webhook billing conflict ignored: {e}")
      return JSONResponse(status_code=200, content={"status": "conflict_ignored"})
  ```

#### 🚨 Recurring Anti-Pattern: Unguarded `int()`/`float()` Casts on Third-Party Data
Directly casting token metrics or usage fields from provider JSON responses (e.g. `int(response["usage"]["prompt_tokens"])`) without handling missing keys or string values like `"unknown"`.

* **Incorrect:**
  ```python
  # BAD: Raises uncaught ValueError/TypeError
  prompt_tokens = int(data["usage"]["prompt_tokens"])
  ```
* **Correct:**
  ```python
  # GOOD: Guarded integer coercion helper
  def safe_int(val: Any, default: int = 0) -> int:
      try:
          return int(val)
      except (TypeError, ValueError, OverflowError):
          return default
  ```

---

### 6. Knowledge Extraction & Published Facts (Site Intelligence)

> This subsystem publishes claims **about a customer's business**. A wrong number here is not a
> bug report, it is a fabricated fact shown to a user as observed evidence. Review it accordingly.

#### 🚨 Recurring Anti-Pattern: `isinstance(x, (int, float))` as a Numeric Guard
`bool` is a subclass of `int`, and Python's JSON decoder accepts `NaN`/`Infinity` by default. Both
sail through the obvious check and format straight into a published value.

* **Incorrect:**
  ```python
  # BAD: JSON `true` publishes as a fee of 1.00; NaN publishes as "INR nan"
  if not isinstance(value, (int, float)):
      return None
  return float(value)
  ```
* **Correct:**
  ```python
  # GOOD: reject bool, non-finite, and ints too large to become a float
  if isinstance(value, bool) or not isinstance(value, (int, float)):
      return None
  try:
      amount = float(value)
  except OverflowError:
      return None
  return amount if math.isfinite(amount) else None
  ```

#### 🚨 Recurring Anti-Pattern: Resolving Ambiguous Real-World Notation
Mapping a symbol or abbreviation shared by several countries to one of them. `Rs`, `Rs.`, and `₨`
(U+20A8, literally named RUPEE SIGN) are used for the Indian, Pakistani, Sri Lankan, and Nepalese
rupee alike. Resolving any of them publishes a guess as an observed fact. Only country-specific
marks (`₹`) may resolve. **Absence of a fact is a finding; an invented one is a defect.**

#### 🚨 Recurring Anti-Pattern: Order-Dependent Text Sanitization Treated as Style
When several strip passes run in sequence, their ORDER is a correctness property. Removing HTML
comments before closed `<script>` subtrees let a bare `<!--` inside a JavaScript string literal
read as an unterminated comment and discard the rest of the document — a content-rich page then
counted zero readable characters and escalated to a browser render as a "JS shell".

* **Rule:** closed non-text subtrees → comments → unterminated subtrees. Any reordering needs a
  test for BOTH directions (a comment containing a script tag, and a script containing `<!--`).

#### 🚨 Recurring Anti-Pattern: Binding a Value to the Wrong Subject
A pack role lists its primary subject FIRST and later entity types as things the page may merely
*mention*. Accepting any declared type let a schema-declared place or offer — identity-keyed by
its own name rather than by the page — capture every amount on the page. Always resolve through
the role's primary type, and check the identity key, not just the type.

#### 🚨 Recurring Anti-Pattern: "Unused" Dependency Audits That Only Grep for Calls
A dependency can be mandatory with no direct import. `python-multipart` has no `import multipart`
anywhere, but FastAPI raises **at route-definition time** when a path declares `UploadFile`, so
removing it fails every test that builds the app. Searching for `UploadFile(` missed the real
usage, a bare type annotation (`file: UploadFile | None`).

* **Rule:** before removing a dependency, run the full suite — do not trust a grep. Framework
  plugins, type-only annotations, and CLI entry points (`uvicorn` in a Dockerfile `CMD`) all have
  zero import sites.

---

## 🤖 Code Reviewing Agent Instructions

When performing automated or pair-programming code reviews on this codebase, agents MUST follow this protocol:

1. **Check Invariant 1 (Config Zero-Tolerance)**:
   - Verify that NO hardcoded URLs, model strings, timeouts, retry counts, or thresholds were added in service, domain, worker, or UI code. Reject immediately if found.

2. **Static Analysis & Type Verification**:
   - Run type checks (`npx tsc --noEmit` in `frontend/`, `mypy` or `pytest` in `backend/`).
   - Check that no new lint or type errors are introduced.

3. **Security & Boundary Scan**:
   - Scan all newly added HTTP endpoints for scheme/host checks on user-configurable URLs.
   - Verify that state-changing endpoints enforce workspace authorization (`require_workspace_member`).

4. **Exception Integrity Verification**:
   - Inspect all `except IntegrityError` or `except Exception` blocks to ensure errors are not swallowed or mapped to inaccurate status codes.

5. **Review Report Formatting**:
   - Classify findings using standard tags: `[Config Zero-Tolerance]`, `[Security & Network]`, `[Database & Integrity]`, `[Validation & Types]`, `[Frontend & UI]`, `[Integrations & Billing]`.
   - Provide concrete "Incorrect" vs "Correct" code snippets for any requested changes.
