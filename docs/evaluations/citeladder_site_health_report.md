# CiteLadder Site Health — High-Value Improvements from MarketingSkills

## Purpose

The strongest idea in the MarketingSkills framework is not a larger checklist of SEO rules. It is the **site-modeling layer that comes before the audit**:

> **Understand the business/site type → classify pages → infer hierarchy → visualize the site → compare actual structure with an expected model → apply page-appropriate SEO/AEO checks.**

CiteLadder already has useful page-level extraction, page-kind classification, schema checks, technical rules, and AEO signals. The biggest opportunity is to make those checks **context-aware at the site level**.

---

## 1. Site Type Classification

Classify every crawled site into a primary operating model, using aggregate crawl evidence rather than only homepage copy.

Recommended site types:

- SaaS / software
- Ecommerce
- Content / publisher
- Documentation / knowledge base
- Hybrid SaaS + content
- Local / service business

Useful evidence includes:

- distribution of product, category, article, pricing, docs, FAQ and other page types
- navigation labels and URL families
- schema types
- commerce signals
- CTAs and site-wide linking patterns

### Value to CiteLadder

A product page, SaaS feature page and local-service page should not be judged against the same structural expectations. Site type becomes the context for all later analysis.

---

## 2. Architecture Role + Page Hierarchy

Keep CiteLadder's existing `page_kind` classification, but add a second concept: **architecture role**.

Example:

```text
page_kind: category
architecture_role: ecommerce_category
hierarchy_level: L2
```

Useful hierarchy levels:

```text
L0  Homepage
L1  Primary sections
L2  Section / category / hub pages
L3+ Detail pages
```

Hierarchy should be inferred from:

1. internal links and navigation
2. breadcrumbs
3. URL structure
4. sitemap relationships
5. canonical and contextual-link evidence

Do not use URL slash depth alone.

### Value to CiteLadder

This gives CiteLadder enough context to detect meaningful structural problems instead of generic isolated page warnings.

---

## 3. ASCII Site Architecture View

Make the site tree a first-class Site Health output.

Example:

```text
Homepage
│
├── Women                         L1
│   ├── Clothing                  L2
│   │   ├── Dresses               L3
│   │   │   └── [142 Products]    L4
│   │   ├── Tops                  L3
│   │   └── Sleepwear             L3
│   └── Accessories               L2
│
├── Men                           L1
├── Kids                          L1
├── Blog                          L1
│   └── [27 Articles]             L2
└── Help                          L1
    ├── Delivery                  L2
    ├── Returns                   L2
    └── Contact                   L2
```

Large page families should collapse into counts rather than rendering hundreds of URLs.

### Value to CiteLadder

The tree gives users an immediate mental model of their website and makes architecture findings much easier to understand than tables of URLs.

---

## 4. Expected vs Observed Architecture

Create reference structures for each site type and compare the crawled architecture with the expected model.

Example for ecommerce:

```text
Expected
Homepage
├── Shop
│   ├── Category
│   │   ├── Subcategory
│   │   └── Product
├── Collections
├── Sale
├── Blog
└── Help
    ├── FAQ
    ├── Shipping
    ├── Returns
    └── Contact
```

CiteLadder should identify structural gaps such as:

- support pages exist but no Help hub
- important categories are buried too deeply
- products have no category parent
- orphan pages
- blog content does not link into commercial sections
- breadcrumbs and site hierarchy disagree
- important page families are missing or weak

### Value to CiteLadder

This converts Site Health from **"what is technically wrong?"** into **"how should this site be structured for its business model?"**

---

## 5. Site-Level Architecture Health

Aggregate findings by structural root cause instead of producing hundreds of duplicate URL warnings.

Example:

```text
HIGH
23 important pages are orphaned.

HIGH
7 category pages require 5+ clicks from the homepage.

MEDIUM
18 products have no clear category parent.

MEDIUM
Shipping, Returns, FAQ and Contact exist but are not grouped under a Help hub.

MEDIUM
Blog-to-product contextual linking is weak.
```

Recommended high-value signals:

- orphan pages
- click depth
- parentless detail pages
- weak hub-to-child linking
- missing hub pages
- internal-link imbalance
- sitemap vs crawl discrepancies
- breadcrumb hierarchy conflicts
- duplicate or competing page families

### Value to CiteLadder

Users see the few structural causes that matter instead of being overwhelmed by symptoms.

---

## 6. Page-Type-Aware SEO, Schema and AEO Audits

Run checks using:

```text
site_type + architecture_role + hierarchy_level + page_kind
```

Examples:

### Ecommerce product

Focus on:

- Product schema
- price / availability / SKU / brand
- category and breadcrumb relationships
- canonical correctness
- product description quality
- related-product linking
- reviews
- AI extractability

### Ecommerce category

Focus on:

- category metadata
- product links
- pagination and facets
- canonical/indexation behavior
- unique category copy
- breadcrumbs
- internal-link strength

### Article / guide

Focus on:

- author and dates
- Article schema
- citations and evidence
- topic coverage
- commercial/internal links
- freshness
- AI answer extractability

### Value to CiteLadder

This removes low-value or irrelevant warnings and makes Site Health recommendations more credible.

---

## 7. Page Family and Programmatic SEO Detection

Automatically group large URL sets into page families such as:

```text
/products/*
/collections/*
/integrations/*
/compare/*
/templates/*
/locations/*
```

For each family, analyze:

- URL count
- template similarity
- unique-content ratio
- metadata duplication
- structural consistency
- indexability
- orphan rate
- internal-link coverage
- schema consistency

Example:

```text
/templates/*
612 URLs
417 share near-identical body structure
88 have duplicate introductions
23 are orphaned
```

### Value to CiteLadder

This is especially valuable for ecommerce and large SaaS sites, where problems are usually template-level rather than isolated to individual pages.

---

## 8. Recommended Site Health Experience

The strongest Site Health output would combine four views:

### A. Site Profile

```text
Site type: Ecommerce
Confidence: 96%
Primary goal: Transactional
Pages analyzed: 487
```

### B. Architecture Tree

ASCII / expandable tree of the crawled website.

### C. Structural Findings

Prioritized site-wide issues such as orphan clusters, excessive depth, missing hubs and weak internal-link relationships.

### D. Contextual Page Findings

Technical SEO, content, schema and AEO checks appropriate to each page's role.

---

## Recommended Product Direction

CiteLadder should **not** become a larger generic SEO checklist.

The highest-value evolution is:

```text
Page checker
    ↓
Site classifier
    ↓
Architecture model
    ↓
Site tree
    ↓
Expected-vs-observed analysis
    ↓
Context-aware SEO / content / schema / AEO audit
```

The most differentiating additions are therefore:

1. **Site type classification**
2. **Architecture-role classification**
3. **Hierarchy inference**
4. **ASCII site tree**
5. **Expected vs observed architecture**
6. **Root-cause architecture findings**
7. **Page-type-aware audits**
8. **Page-family / programmatic SEO analysis**

These features build directly on CiteLadder's existing crawler and page-classification foundation while turning Site Health into a much more useful **site intelligence and improvement product**.

---

## Reference

Framework reviewed:

https://github.com/coreyhaines31/marketingskills

Most relevant sections:

- `skills/site-architecture/`
- `skills/seo-audit/`
- `skills/schema/`
- `skills/programmatic-seo/`
- `skills/content-strategy/`
- `skills/ai-seo/`
