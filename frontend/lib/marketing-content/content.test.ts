// @vitest-environment node
//
// Pure logic: no DOM, no window, no React render. The suite-wide jsdom
// default costs a full environment per file and buys nothing here.
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { POSTS, type BlogBlock } from './blog';
import { COMPETITORS, FACT_ROWS, FAIRNESS_POINTS } from './compare';
import { FAQ_GROUPS } from './faq';
import {
  AI_POLICY,
  COOKIE_POLICY,
  FOOTER_LEGAL_LINKS,
  PRIVACY_POLICY,
  TERMS_OF_SERVICE,
  type LegalDocument,
} from './legal';
import { DEMO_CTA, DEMO_HREF, NAV_DROPS, NAV_LINKS, type NavDropItem } from './nav';
import { PLAN_PRESENTATION, capabilityLabel } from './pricing';
import { SOLUTION_SEGMENTS } from './solutions';

/**
 * `lib/marketing-content` is the public surface's copy, and it had no tests.
 *
 * These are STRUCTURAL, not snapshots. A snapshot of 1,500 lines of marketing
 * copy fails on every deliberate wording change and proves nothing; what is
 * actually worth catching is a route that does not exist, a duplicate blog
 * slug, an empty section that renders as a blank block, and — the rule the
 * repository already enforces at E2E level — a commercial page claiming the
 * product is open source or self-hostable.
 */
const ALL_LEGAL: readonly LegalDocument[] = [
  PRIVACY_POLICY,
  TERMS_OF_SERVICE,
  COOKIE_POLICY,
  AI_POLICY,
];

/** Every internal href declared anywhere in the marketing content. */
function internalHrefs(): string[] {
  const fromDrops = NAV_DROPS.flatMap((drop) => [
    drop.href,
    ...drop.groups.flatMap((group) =>
      group.items
        .filter((item: NavDropItem) => !('external' in item && item.external))
        .map((item) => item.href),
    ),
  ]);
  return [
    ...fromDrops,
    ...NAV_LINKS.map((link) => link.href),
    ...FOOTER_LEGAL_LINKS.map((link) => link.href),
    DEMO_HREF,
  ];
}

function blockText(block: BlogBlock): string {
  return block.type === 'list' ? block.items.join(' ') : block.text;
}

function marketingRouteFile(href: string): string {
  const pathname = href.split('#', 1)[0].replace(/^\//, '');
  return resolve(import.meta.dirname, '../../app/(marketing)', pathname, 'page.tsx');
}

function stringsIn(value: unknown): string[] {
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.flatMap(stringsIn);
  if (value && typeof value === 'object') return Object.values(value).flatMap(stringsIn);
  return [];
}

describe('marketing navigation', () => {
  it('routes every internal link from the site root', () => {
    // Anchors are absolute (`/#see-it`) so a row resolves from a subpage,
    // not only from `/`.
    for (const href of internalHrefs()) {
      expect(href, href).toMatch(/^\/(?:$|[a-z0-9#/-])/);
      expect(existsSync(marketingRouteFile(href)), href).toBe(true);
    }
  });

  it('gives every dropdown a unique key and a non-empty label', () => {
    const keys = NAV_DROPS.map((drop) => drop.key);
    expect(new Set(keys).size).toBe(keys.length);
    for (const drop of NAV_DROPS) {
      expect(drop.label.trim(), drop.key).not.toBe('');
      expect(drop.groups.length, drop.key).toBeGreaterThan(0);
    }
  });

  it('gives every dropdown row a title, a description, and a destination', () => {
    for (const drop of NAV_DROPS) {
      for (const group of drop.groups) {
        expect(group.items.length, drop.key).toBeGreaterThan(0);
        for (const item of group.items) {
          expect(item.title.trim(), `${drop.key}/${item.href}`).not.toBe('');
          expect(item.desc.trim(), `${drop.key}/${item.title}`).not.toBe('');
          expect(item.href.trim(), `${drop.key}/${item.title}`).not.toBe('');
        }
      }
    }
  });

  it('keeps exactly one demo destination for the funnel', () => {
    expect(DEMO_HREF).toBe('/demo');
    expect(DEMO_CTA.trim()).not.toBe('');
  });
});

describe('pricing content', () => {
  it('blurbs every plan key', () => {
    for (const [key, plan] of Object.entries(PLAN_PRESENTATION)) {
      expect(plan.blurb.trim(), key).not.toBe('');
    }
  });

  it('highlights exactly one plan', () => {
    // Two highlighted plans is a layout bug that reads as an unmade decision.
    const highlighted = Object.values(PLAN_PRESENTATION).filter((plan) => plan.highlighted);
    expect(highlighted).toHaveLength(1);
  });

  it('humanises an unmapped capability key instead of rendering nothing', () => {
    // A capability key the backend adds must still produce a readable string:
    // the helper returns a string in every branch so React can render it.
    expect(capabilityLabel('a_brand_new_capability')).toBe('A brand new capability');
    expect(capabilityLabel('')).toBe('');
  });
});

describe('blog content', () => {
  it('has unique slugs', () => {
    // A duplicate slug makes one post permanently unreachable at
    // `/blog/[slug]`.
    const slugs = POSTS.map((post) => post.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it('uses url-safe slugs', () => {
    for (const post of POSTS) {
      expect(post.slug, post.title).toMatch(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);
    }
  });

  it('gives every post a title, an excerpt, a tag, and a body', () => {
    for (const post of POSTS) {
      expect(post.title.trim(), post.slug).not.toBe('');
      expect(post.excerpt.trim(), post.slug).not.toBe('');
      expect(post.tags.length, post.slug).toBeGreaterThan(0);
      expect(post.body.length, post.slug).toBeGreaterThan(0);
    }
  });

  it('renders no empty block', () => {
    for (const post of POSTS) {
      for (const block of post.body) {
        expect(blockText(block).trim(), `${post.slug}/${block.type}`).not.toBe('');
      }
    }
  });

  it('omits optional byline fields rather than storing a placeholder', () => {
    // The module's rule: while a byline field is absent the row is omitted, so
    // an empty string would render an empty byline instead of none.
    for (const post of POSTS) {
      for (const field of ['date', 'readTime', 'author'] as const) {
        const value = post[field];
        if (value !== undefined) expect(value.trim(), `${post.slug}.${field}`).not.toBe('');
      }
    }
  });
});

describe('comparison content', () => {
  it('names every competitor uniquely', () => {
    const names = COMPETITORS.map((competitor) => competitor.name);
    expect(new Set(names).size).toBe(names.length);
  });

  it('states the fairness position and the fact rows', () => {
    expect(FAIRNESS_POINTS.length).toBeGreaterThan(0);
    expect(FACT_ROWS.length).toBeGreaterThan(0);
  });
});

describe('faq and solutions content', () => {
  it('gives every FAQ group at least one answered question', () => {
    expect(FAQ_GROUPS.length).toBeGreaterThan(0);
    for (const group of FAQ_GROUPS) {
      expect(group.items.length, group.heading).toBeGreaterThan(0);
      for (const item of group.items) {
        expect(item.q.trim(), group.heading).not.toBe('');
        expect(item.a.trim(), item.q).not.toBe('');
      }
    }
  });

  it('gives every solution segment a renderable scene', () => {
    const scenes = new Set(['share', 'health', 'sample', 'commerce', 'citations']);
    expect(SOLUTION_SEGMENTS.length).toBeGreaterThan(0);
    for (const segment of SOLUTION_SEGMENTS) {
      expect(scenes.has(segment.scene), segment.scene).toBe(true);
    }
  });
});

describe('legal content', () => {
  it('publishes each policy under a distinct slug', () => {
    const slugs = ALL_LEGAL.map((document) => document.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it('links every published policy from the footer', () => {
    // A policy with no route out of the footer is effectively unpublished.
    const linked = new Set(FOOTER_LEGAL_LINKS.map((link) => link.href.replace(/^\//, '')));
    for (const document of ALL_LEGAL) {
      expect(linked.has(document.slug), document.slug).toBe(true);
    }
  });

  it('gives every section an id, a title, and some content', () => {
    for (const document of ALL_LEGAL) {
      expect(document.sections.length, document.slug).toBeGreaterThan(0);
      for (const section of document.sections) {
        expect(section.id.trim(), `${document.slug}/${section.title}`).not.toBe('');
        expect(section.title.trim(), `${document.slug}/${section.id}`).not.toBe('');
        const hasContent =
          (section.paragraphs?.length ?? 0) > 0 ||
          (section.bullets?.length ?? 0) > 0 ||
          Boolean(section.note?.trim());
        expect(hasContent, `${document.slug}/${section.id}`).toBe(true);
      }
    }
  });

  it('uses unique section ids within a document so anchors resolve', () => {
    for (const document of ALL_LEGAL) {
      const ids = document.sections.map((section) => section.id);
      expect(new Set(ids).size, document.slug).toBe(ids.length);
    }
  });
});

describe('commercial positioning', () => {
  const everyString = [
    ...POSTS.flatMap((post) => [post.title, post.excerpt, ...post.body.map(blockText)]),
    ...FAQ_GROUPS.flatMap((group) => group.items.flatMap((item) => [item.q, item.a])),
    ...Object.values(PLAN_PRESENTATION).map((plan) => plan.blurb),
    ...stringsIn(COMPETITORS),
    ...stringsIn(FAIRNESS_POINTS),
    ...stringsIn(FACT_ROWS),
    ...ALL_LEGAL.flatMap((document) =>
      document.sections.flatMap((section) => [
        ...(section.paragraphs ?? []),
        ...(section.bullets ?? []),
        section.note ?? '',
      ]),
    ),
  ].join('\n');

  it.each(['MIT license', 'open source', 'open-source', 'self-host', 'github.com'])(
    'makes no %j claim',
    (phrase) => {
      // CiteLadder is a commercial product. The E2E suite asserts this on the
      // rendered pages; this catches it in the content module, where it is
      // cheaper to find and impossible to miss on a page nobody screenshots.
      expect(everyString.toLowerCase()).not.toContain(phrase.toLowerCase());
    },
  );
});
