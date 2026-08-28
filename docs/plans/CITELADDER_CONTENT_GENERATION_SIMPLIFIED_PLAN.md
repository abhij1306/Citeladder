# CiteLadder Content Generation — Simplified Demo-First Improvement Plan

**Audience:** Codex / implementation agent
**Goal:** Make CiteLadder content generation produce logical, grounded, useful content for the upcoming demos without turning the feature into a complex agentic content system.

**Decision update (2026-08-28):** production Content Generation uses only config-approved frontier
model routes. The former MiniMax M3/GMI demo mandate is superseded. Tavily, MiniMax, GLM, and other
evaluation scaffolds are not production Content providers and never supply product visibility
evidence.

---

## 1. Objective

Improve the existing Content Generation feature while keeping the user experience and backend architecture simple.

The intended product flow is:

```text
User chooses what to create
        ↓
Choose curated content skill
        ↓
Build useful context from:
- Brand/project data
- Relevant Site Crawl content
- GSC data when connected
- Frozen Opportunity handoff when generation starts from an action
        ↓
ONE approved frontier-model generation call
        ↓
Editable / copyable generated content
```

For the current demos, **Site Crawl must be sufficient by itself** because GSC will not necessarily be available.

When GSC is available later, it should improve the same generation flow rather than create a second content-generation architecture.

---

# 2. Explicit Non-Goals

Do **not** add any of the following for this iteration:

- LLM judges
- content auditors
- critic agents
- autonomous research agents
- multi-agent pipelines
- section-by-section generation pipelines
- complex provenance workflows
- user-facing evidence graphs
- approval workflows
- multiple generation passes by default
- complicated source-management screens
- new content inventory systems

The goal is not to build an enterprise CMS.

The goal is:

> **Give the approved frontier model the right brand context, the right relevant website/GSC or Opportunity evidence, and a good platform-specific skill prompt, then generate the content once.**

---

# 3. Keep the Existing Foundation

The existing feature already has useful infrastructure that should remain:

- content generation queue
- generation history
- retry / regenerate
- skill catalogue
- project scoping
- crawl grounding
- provider abstraction
- Markdown rendering
- copy/export
- optional opportunity linkage
- Search Demand → Content flow

Do not rewrite these systems unless required by the changes below.

---

# 4. Main Problems to Fix

## 4.1 Crawl context is selected without enough relevance

The current crawl context selection is deterministic but primarily prioritises:

```text
homepage
→ monitored URLs
→ other URLs
```

This is not good enough for generation.

Example:

```text
Prompt:
"Write a guide to choosing kids school uniforms for summer"

Current context may contain:
- homepage
- delivery page
- generic monitored pages
- unrelated categories

Useful context should instead contain:
- schoolwear category
- school polos
- school shorts
- sizing guide
- relevant product/category copy
```

### Required change

Keep the existing crawl data.

Change only **how pages/fragments are selected for content generation**.

The selector should receive the user's generation prompt and, when applicable:

- target URL
- target query
- demand signal
- opportunity target/theme

Then rank available crawl pages for relevance.

A simple implementation is enough.

Suggested ranking signals:

```text
1. Explicit target URL                           highest priority
2. URL/title/H1/H2 keyword overlap
3. Body-text keyword overlap
4. Page type relevance
5. Homepage as fallback/background context
```

Do not introduce embeddings/vector DB infrastructure for the demo unless it already exists and can be reused trivially.

A deterministic lexical relevance score is sufficient.

### Suggested context budget

Instead of blindly selecting the first 10 pages:

```text
Target page if present: always include
Top relevant pages:     5–10
Homepage:               include only if useful for brand context
```

Keep the context within the configured model budget; relevance matters more than raw size.

---

# 5. Generation Context

Create one simple object before calling the model.

Suggested shape:

```python
ContentGenerationContext(
    brand=...,
    user_instruction=...,
    skill=...,
    target_url=...,
    target_query=...,
    opportunity_handoff=...,
    site_pages=[...],
    gsc_context=...,
)
```

This is an internal context builder, not a new persistent product domain.

The model should receive clearly separated sections:

```text
1. BRAND
2. TASK
3. OPPORTUNITY EVIDENCE (only when supplied)
4. RELEVANT WEBSITE CONTENT
5. SEARCH PERFORMANCE DATA (only when available)
```

---

# 6. Brand Context

Use the brand/project information CiteLadder already knows.

Include, when available:

- brand name
- website
- description
- positioning
- products/services
- target audience
- market / locale
- language
- confirmed project/brand information

Do not require every field to be manually confirmed before the model can write naturally.

The purpose of this context is to help the generation model:

- understand who it is writing for
- use correct brand terminology
- avoid generic output
- maintain the right market/locale

Brand Profile remains **context**, not another content-data integration.

The evidence inputs remain owned by their existing domains:

1. Site Crawl for observed owned-site facts.
2. GSC for optional observed demand evidence.
3. Opportunity handoff for the exact persisted action evidence and provenance.

---

# 7. Site Crawl as the Primary Demo Source

Site Crawl must support useful generation even with zero GSC data.

For each selected relevant page send the generation model a compact representation:

```text
URL
Title
Meta description
H1
Important H2s
Relevant body text
```

Example:

```text
SOURCE: https://example.com/schoolwear

Title:
School Uniforms & Schoolwear

H1:
School Uniforms

Relevant content:
...
```

Avoid sending internal JSON/provenance structures when plain structured text is easier for the model to understand.

The generation model should be told:

```text
Use the supplied website material as factual brand/product context.
Do not invent specific prices, policies, guarantees, statistics or product
attributes that are not present in the supplied context.
If a detail is unavailable, normally omit it rather than writing
"information unavailable" into the public content.
```

This keeps grounding without making the output sound like a compliance report.

---

# 8. GSC Improvements

GSC should enhance generation when connected, but Content must not depend on it.

## 8.1 Query-driven generation

When content originates from a GSC/Search Demand query, include:

```text
Target query
Impressions
Clicks
CTR
Average position
Relevant page currently ranking
Other relevant queries for that page/topic
```

The existing Search Demand brief logic is useful and should be retained/simplified.

Do not send every metric available.

Send only data that helps the model understand:

```text
what users are searching for
what page currently serves them
what should be improved
```

---

## 8.2 Existing-page rewrite

For page-rewrite content:

```text
GSC
→ identify query / performance problem

Site Crawl
→ provide the actual target page content

Approved frontier model
→ rewrite/improve the page
```

This combination is much more useful than GSC alone.

The target page must always be included in crawl context.

---

## 8.3 New-content generation

For a query with no suitable page:

```text
GSC target query
+
related GSC queries where available
+
topically relevant crawl pages
+
brand context
→ new content
```

This lets CiteLadder create content that fills an actual content gap while still understanding the existing website.

---

# 9. Opportunity → Content Fix

Keep this simple.

An opportunity can be linked to a generation. The generation must also receive the exact useful
evidence projected by the Opportunity owner.

When `opportunity_id` exists, include:

```text
Opportunity title
Opportunity remediation
Action pathway and source class
Canonical earned domain when applicable
Target URL
Target theme
Representative cited page URLs/titles
Affected prompts/themes and observed competitors
Coverage, limitations, truncation state, exact source-analysis IDs, and versions
```

Do not build a new Opportunity agent or parallel brief store. Consume the typed, bounded
`content_handoff` from the existing Opportunity detail contract and freeze it in the generation
context manifest.

Convert the opportunity into a small text block and add it to the task context.

Example:

```text
CONTENT OPPORTUNITY

Issue:
Competitors are being cited more often for school-uniform sizing queries.

Recommended action:
Create stronger sizing guidance answering common buyer questions.

Target theme:
School uniform sizing
```

The Opportunities drawer routes to Content with `opportunity_id` and labels the action **Create
owned content** or **Prepare earned content**. Content shows the supplied evidence, preselects the
server-suggested skill, and seeds an editable instruction once without overwriting user edits.

For earned work, initial outputs are transparent editorial inclusion briefs, expert-contribution
outlines, review/profile evidence packs, or outreach drafts. They never impersonate an independent
customer, fabricate first-person experience, or autonomously post, send, or publish.

After a successful generation, Content links back to the Opportunity. An implementation declaration
may attach `generation_id`; the backend accepts it only when it belongs to the same workspace,
project, and opportunity and has an eligible successful status. Drafting or sending an earned pitch
keeps the Opportunity `in_progress`; only the user declares a public implementation.

---

# 10. Curated Content Skills

Keep the existing skill catalogue.

Improve the prompts rather than replacing the system.

The skill should define only:

```text
Purpose
Output format
Structure
Tone
Length guidance
Platform-specific constraints
```

The skill should **not** contain excessive generic grounding instructions. Grounding rules should live in the common system prompt.

---

## Recommended skill structure

Each skill can conceptually contain:

```python
ContentSkill(
    id="linkedin",
    purpose="Create a professional LinkedIn post",
    structure=[...],
    tone="...",
    length="...",
    rules=[...],
)
```

---

## High-priority skills for the demos

Retain all existing skills, but focus tuning/testing on:

### Website Content Page

Should produce:

```text
H1
opening answer/value proposition
logical H2/H3 sections
tables/lists only when useful
CTA
optional meta title
optional meta description
```

Avoid forcing a large "Sources" section into normal publishable copy.

---

### Article / Blog

Must:

- answer the subject early
- avoid generic introductions
- use website-specific information where available
- use useful headings
- write naturally
- avoid repeating the brand name unnecessarily
- avoid filler conclusions

---

### FAQ

Must:

- generate natural questions
- give direct standalone answers
- use actual brand/site information
- avoid inventing policy/product facts
- be suitable for search and AI-answer extraction

---

### Comparison

Must:

- clearly define compared options
- avoid fabricated competitor/product facts
- use only supplied comparison evidence when discussing factual differences
- produce a useful table when appropriate

If competitor evidence has not been supplied, do not invent competitor specifications.

---

### LinkedIn

Must:

- contain one clear idea
- have a strong opening
- avoid obvious AI-style formatting
- avoid fake personal anecdotes
- avoid excessive hashtags
- reuse useful brand/site insight rather than simply advertising the company

---

### Reddit

Must:

- sound conversational
- avoid obvious promotional language
- avoid fabricated first-person experience
- avoid pretending the brand is an independent user
- focus on useful information

---

### YouTube

Must:

- create spoken-language output
- have a direct hook
- have logical sections
- use site/brand facts naturally
- avoid bloated intros

---

## Skill cleanup

Review the existing catalogue and remove unnecessary or questionable platform folklore.

Examples:

- unsupported claims about algorithms
- arbitrary formatting rules that reduce output quality
- instructions that conflict with the user's request
- repetitive grounding rules already handled globally

Skills should be **short, opinionated templates**, not giant prompts.

---

# 11. Frontier content-provider policy

Production Content Generation uses the existing provider-neutral transport with a config-owned
allowlist of approved frontier generation routes. Provider, requested model, returned model,
reasoning policy, request configuration, usage, and attempt status are frozen as generation
provenance.

The Content provider identity is separate from the logical engine/provider identity of any
visibility audit. Generating a draft never changes or impersonates the engine observation that
created an Opportunity.

Do not silently fall back to Tavily, MiniMax, GLM, model-invented citations, or another synthetic
route. If no approved frontier route is configured or available, generation fails explicitly and
the frozen context remains inspectable.

Extend the existing content provider abstraction only when an approved frontier endpoint requires
it. Configuration selects the transport and exact model; service code does not hardcode provider
policy:

```text
provider = <approved frontier provider>
model = <approved frontier model>
base_url = <approved endpoint when applicable>
api_key = ...
```

Provider credentials remain secret, are resolved only by the owning connector, and never enter
DTOs, context snapshots, logs, or generated artifacts. Tests inject fake configuration and mock
provider I/O; they never read `.env`.

---

# 12. Simplified Prompt Architecture

Use **one generation request**.

Suggested message layout:

```text
SYSTEM

You are CiteLadder's content writer.

Create useful, publishable content that satisfies the user's task and the
selected content format.

Use supplied brand and website/search data as factual context.

Do not invent:
- prices
- product specifications
- policies
- guarantees
- statistics
- customer claims
- competitor facts

If a specific factual detail is not available, omit it or write around it
naturally. Do not insert "information unavailable" into publishable content
unless the user explicitly asks for a factual report.

Write naturally and specifically. Avoid generic AI filler.
```

Then:

```text
SKILL

[Rendered concise skill instructions]
```

Then:

```text
BRAND CONTEXT

...
```

Then:

```text
TASK

[user prompt / demand brief / opportunity instruction]
```

Then:

```text
RELEVANT WEBSITE CONTENT

...
```

Then, only when connected:

```text
GOOGLE SEARCH CONSOLE CONTEXT

...
```

One call.

One final draft.

---

# 13. User Experience

The UI should remain simple.

Do not expose the internal context-building machinery.

## Main screen mockup

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Content                                                             │
│ Create content using what CiteLadder already knows about your brand │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ What do you want to create?                                         │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ Write a guide to choosing school uniforms for summer            │ │
│ │                                                                 │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Format                                                              │
│ [ Website Page ] [ Blog ] [ FAQ ] [ LinkedIn ] [ Reddit ] [ More ] │
│                                                                     │
│ Context being used                                                  │
│ ✓ Website crawl: 8 relevant pages                                  │
│ ○ Search Console: Not connected                                    │
│                                                                     │
│                                         [ Generate content ]        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

No evidence selection UI is required for the demo.

CiteLadder should automatically choose relevant crawl pages.

---

# 14. GSC-Connected UI

When GSC is available:

```text
Context being used

✓ Website crawl: 6 relevant pages
✓ Search Console: "school uniform sizing"
  12.4K impressions · position 9.3
```

If the generation originated from Search Demand, automatically populate this.

Do not force the user to manually configure GSC context again.

---

# 15. Opportunity-Origin UI

When coming from an opportunity:

```text
┌───────────────────────────────────────────────────────┐
│ Based on opportunity                                  │
│                                                       │
│ Improve coverage for school-uniform sizing questions │
│ Competitors are being cited more consistently.       │
└───────────────────────────────────────────────────────┘

[editable generation instruction]

Format
[ Blog ▼ ]

✓ Website crawl: 7 relevant pages

[ Generate content ]
```

The important difference from the current implementation is that the frozen Opportunity handoff
must actually be supplied to the approved frontier model and remain inspectable in Content.

---

# 16. Result UI

Keep the result experience lightweight.

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Generated content                                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ # How to Choose the Right School Uniform Size                      │
│                                                                     │
│ ...generated Markdown...                                            │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ Grounded with: Website crawl · 7 pages                              │
│ Opportunity: Earned · example.com · 3 cited pages                  │
│                                                                     │
│ [ Copy ] [ Export Markdown ] [ Regenerate ] [ Return to opportunity ]│
│                                                                     │
│ Was this useful?   [ Yes ] [ No ]                                  │
└─────────────────────────────────────────────────────────────────────┘
```

Optional small improvement:

When the user clicks **No**, show:

```text
Why?
[ Too generic ]
[ Wrong tone ]
[ Missed the topic ]
[ Incorrect facts ]
[ Other ]
```

This is useful feedback but should not block the demo.

---

# 17. Context Selection Implementation

Add a content-specific relevance selector rather than rewriting Site Health.

Suggested interface:

```python
select_content_context(
    session,
    workspace_id,
    project_id,
    query_text,
    target_url=None,
)
```

## Basic scoring

For every usable crawled page:

```text
score = 0

if page.url == target_url:
    score += 1000

score += title_overlap * 20
score += h1_overlap * 20
score += h2_overlap * 10
score += url_overlap * 10
score += body_overlap * 2
```

Normalise prompt terms:

- lowercase
- tokenize
- remove common stop words
- optionally stem very lightly

Then choose the highest-scoring pages.

This is intentionally simple.

Do not introduce a vector database solely for this feature before the demos.

---

# 18. Important Rewrite Behaviour

If the prompt refers to an existing URL:

```text
Rewrite:
https://example.com/category/schoolwear
```

or the GSC/opportunity target contains a URL:

that page must be included first.

Then add related crawl pages for supporting context.

Example:

```text
1. exact target page
2. related category page
3. relevant products
4. relevant guide/FAQ
5. brand/home context if useful
```

This will materially improve rewrite quality.

---

# 19. Output Quality Rules

The global prompt should enforce a small set of quality rules.

## Required

- answer the requested subject directly
- use specific brand/site information where relevant
- do not fabricate factual specifics
- follow the selected format
- use the project's locale/language
- avoid generic AI introductions
- avoid unnecessary repetition
- omit unsupported details naturally

## Avoid

Typical filler such as:

```text
"In today's fast-paced world..."
"When it comes to..."
"Whether you're a seasoned professional or just getting started..."
"Look no further..."
"Game-changing..."
"Revolutionary..."
```

Do not maintain a huge blacklist.

A concise instruction is enough.

---

# 20. Demo Behaviour Without GSC

The Feedonomics and Best&Less demos must work with:

```text
Brand data
+
Site Crawl
+
Approved frontier content model
```

Example demo flow:

```text
1. Open Content
2. Enter:
   "Write a buyer guide for choosing kids schoolwear for warmer weather"
3. Select Blog
4. UI shows:
   Website crawl · 8 relevant pages
   Search Console · Not connected
5. Generate
6. The approved frontier model receives relevant schoolwear/category/product content
7. Output contains brand-specific, grounded information
```

The absence of GSC must not appear as an error or degraded-state warning.

It is simply an unavailable optional source.

---

# 21. Demo Behaviour With GSC Later

When GSC is connected:

```text
User opens Search Demand
→ selects opportunity/query
→ Create Content
→ prompt is prefilled
→ target query + metrics are included
→ relevant target/site pages are selected from crawl
→ selected skill is prefilled
→ Generate
```

The user should experience this as the same feature with better context.

---

# 22. Minimal Backend Changes

Primary files/modules expected to change:

```text
backend/app/core/config/content.py
backend/app/core/config/content_skills.py
backend/app/domain/content/website_context.py
backend/app/domain/content/grounding.py
backend/app/domain/content/message_builder.py
backend/app/domain/content/service.py
backend/app/workers/content_worker.py
backend/app/connectors/discovery_models/
```

Possible new small module:

```text
backend/app/domain/content/context_builder.py
```

Its responsibility should only be:

```text
brand context
+
task context
+
relevant crawl context
+
optional GSC context
```

Do not create a large hierarchy of planners/judges/agents.

---

# 23. Minimal Frontend Changes

Likely areas:

```text
frontend/components/content/content-screen.tsx
frontend/components/content/content-screen-panels.tsx
frontend/components/content/skill-picker.tsx
frontend/components/content/content-screen-data.ts
frontend/lib/demand/content-brief.ts
```

Add:

- clearer content input
- improved skill picker
- small "Context being used" indicator
- opportunity summary when applicable
- GSC query summary when applicable

Do not build a full document editor for this demo iteration.

Existing rendered Markdown + Copy + Export + Regenerate is sufficient.

---

# 24. Testing

Keep tests focused on actual behaviour.

## Required backend tests

### Crawl relevance

Given pages:

```text
/
/shipping
/schoolwear
/school-polos
/womens-dresses
```

and prompt:

```text
"school uniform sizing guide"
```

the selected context should prioritise:

```text
/schoolwear
/school-polos
```

rather than `/shipping`.

---

### Target URL

When target URL exists, it must always be included.

---

### Site-crawl-only generation

Generation succeeds with:

```text
crawl data present
GSC absent
```

---

### GSC-enhanced generation

When GSC context exists, the generated provider request contains:

```text
target query
relevant metrics
target page
```

---

### Opportunity generation

When `opportunity_id` is supplied, its meaningful content must appear in the model request.

Do not test merely that the ID is persisted.

---

### Skill prompts

For each skill verify:

- correct format instruction is included
- common grounding rule is included once
- skill prompt is not duplicated
- platform-specific structure is present

---

### Approved frontier provider

Mock the OpenAI-compatible endpoint and verify:

```text
model = configured allowlisted frontier model
messages are correct
API key never enters persisted output
response is parsed through existing generation flow
disallowed providers and returned-model mismatches fail explicitly
```

### Opportunity lifecycle linkage

Verify that the Content request freezes the server-projected handoff, a successful generation can
return to the originating Opportunity, and an implementation declaration rejects foreign,
unrelated, or failed generations. A generated or sent earned draft remains `in_progress` until the
user explicitly declares implementation.

---

# 25. Demo Priority

Implement in this order.

## P0 — Required before demo

1. Configure and enforce the approved frontier Content provider/model allowlist.
2. Make crawl context selection relevant to the generation prompt.
3. Always include target URL when rewriting.
4. Simplify grounding instructions so unsupported details are omitted rather than surfaced as "unavailable".
5. Improve/tighten the major content skills.
6. Ensure opportunity details are actually supplied to generation.
7. Show simple context indicator in UI.
8. Verify site-crawl-only generation end-to-end.

## P1 — Strongly desirable

9. Improve GSC context packaging.
10. Ensure Search Demand → Content automatically supplies query metrics + target page.
11. Add small negative-feedback reason selector.

## P2 — After demos

12. Better editing UX.
13. More sophisticated semantic retrieval only if lexical retrieval proves insufficient.
14. Provider/model comparison based on actual generated examples.
15. Deeper content quality evaluation.

---

# 26. Definition of Done

The feature is ready for the demos when the following scenario works reliably:

```text
Project has completed site crawl
        ↓
User opens Content
        ↓
Writes a topic
        ↓
Selects a curated skill
        ↓
CiteLadder automatically picks relevant pages
        ↓
UI tells user that website crawl context is being used
        ↓
The approved frontier model receives:
- brand context
- user task
- skill instructions
- relevant site content
- optional GSC context
        ↓
One generation call
        ↓
Logical, brand-specific, grounded content appears
        ↓
User can Copy / Export / Regenerate
```

When GSC exists, the exact same flow simply gains search-query/performance context.

---

# 27. Core Design Rule

Do not turn Content Generation into an agent platform.

The implementation should remain:

```text
GOOD INPUT
+
GOOD CONTEXT SELECTION
+
GOOD CURATED SKILL
+
STRONG MODEL
=
GOOD OUTPUT
```

Model quality does not replace evidence quality. Improve **what CiteLadder sends to the approved
frontier model**, preserve the frozen context and provenance, and do not surround the model with
unnecessary layers.
