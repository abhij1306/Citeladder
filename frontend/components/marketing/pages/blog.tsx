import { ArrowLeft, ArrowRight, PenLine } from 'lucide-react';
import Link from 'next/link';

import {
  BLOG_EMPTY_STATE,
  POSTS,
  type BlogBlock,
  type BlogPost,
} from '@/lib/marketing-content/blog';
import { DEMO_CTA, DEMO_HREF } from '@/lib/marketing-content/nav';

import { Badge } from '../primitives/badge';
import { ButtonLink } from '../primitives/button';
import { Eyebrow, Meta } from '../primitives/label';
import { PageHero } from '../primitives/page-hero';
import { Container, Section } from '../primitives/section';
import { Reveal, StaggerGroup, StaggerItem } from '../primitives/reveal';
import { blogPostingJsonLd } from '@/lib/seo/json-ld';

import { JsonLd } from '../seo/json-ld';

/**
 * `/blog` and `/blog/[slug]`.
 *
 * Heading rule: post titles render as paragraphs carrying role="heading" +
 * aria-level rather than as literal h2/h3 — a title may contain "Searchify"
 * and no h2–h6 on the marketing surface may, so heading queries stay
 * unambiguous. Assistive tech still gets the intended outline.
 */
function TagRow({ tags }: Readonly<{ tags: readonly string[] }>) {
  return (
    <div className="mb-4 flex flex-wrap gap-2">
      {tags.map((tag) => (
        <Badge key={tag}>{tag}</Badge>
      ))}
    </div>
  );
}

function PostMeta({ post }: Readonly<{ post: BlogPost }>) {
  // Byline fields are owner-supplied; the row is omitted entirely while both
  // are absent, and a single present value renders without the separator.
  const parts = [post.date, post.readTime].filter((value): value is string => Boolean(value));
  if (parts.length === 0) return null;
  return (
    <Meta as="p" className="mt-5">
      {parts.join(' · ')}
    </Meta>
  );
}

function BlogCta({
  title,
  secondary,
}: Readonly<{ title: string; secondary: { href: string; label: string } }>) {
  return (
    <Section tone="field" rhythm="loose" aria-label="Get started">
      <Reveal className="mx-auto max-w-5xl text-center">
        <h2 className="font-mkt-display text-mkt-d2 text-mkt-ink mx-auto mb-5 max-w-[32ch]">
          {title}
        </h2>
        <p className="text-mkt-lead text-mkt-ink-soft mx-auto max-w-[80ch]">
          Walk through your own category — your prompts, your competitors, and the raw answers
          behind every score.
        </p>
        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <ButtonLink href={DEMO_HREF} className="w-full sm:w-auto">
            {DEMO_CTA}
            <ArrowRight aria-hidden />
          </ButtonLink>
          <ButtonLink href={secondary.href} intent="secondary" className="w-full sm:w-auto">
            {secondary.label}
          </ButtonLink>
        </div>
      </Reveal>
    </Section>
  );
}

export function BlogIndex() {
  const [featured, ...rest] = POSTS;
  return (
    <>
      <PageHero
        centered
        eyebrow="The Searchify blog"
        title="Notes on"
        accent="AI visibility."
        lead="Essays, release notes and field reports on answer-engine optimization — evidence-first, and straight from the team building Searchify."
      />

      {featured ? (
        <>
          <Section rhythm="tight" aria-label="Featured post">
            <Reveal className="rounded-mkt-lg bg-mkt-surface shadow-card grid overflow-hidden lg:grid-cols-[1.2fr_0.8fr]">
              <div className="p-8 md:p-10">
                <TagRow tags={featured.tags} />
                <p
                  role="heading"
                  aria-level={2}
                  className="font-mkt-display text-mkt-d3 text-mkt-ink max-w-[32ch]"
                >
                  <Link href={`/blog/${featured.slug}`}>{featured.title}</Link>
                </p>
                <p className="text-mkt-body text-mkt-ink-soft mt-4 max-w-[80ch]">
                  {featured.excerpt}
                </p>
                <PostMeta post={featured} />
              </div>
              {/* Cover art is owner-supplied per post; until a cover field
                  exists the slot stays as plain wallpaper — a shipped page
                  must not carry placeholder chrome. */}
              <div className="mkt-wallpaper grid min-h-[14rem] place-items-center p-8" />
            </Reveal>
          </Section>

          {rest.length > 0 && (
            <Section tone="paper" rhythm="tight" aria-label="All posts">
              <div className="border-mkt-line-soft mb-6 flex items-center justify-between gap-4 border-b pb-4">
                <Meta as="p">All notes</Meta>
                <Meta>
                  {rest.length} {rest.length === 1 ? 'post' : 'posts'}
                </Meta>
              </div>
              <StaggerGroup className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {rest.map((post) => (
                  <StaggerItem
                    key={post.slug}
                    className="rounded-mkt-lg bg-mkt-surface shadow-card h-full p-8"
                  >
                    <TagRow tags={post.tags} />
                    <p
                      role="heading"
                      aria-level={3}
                      className="font-mkt-display text-mkt-ink text-mkt-d5"
                    >
                      <Link href={`/blog/${post.slug}`}>{post.title}</Link>
                    </p>
                    <p className="text-mkt-sm text-mkt-ink-soft mt-3">{post.excerpt}</p>
                    <PostMeta post={post} />
                  </StaggerItem>
                ))}
              </StaggerGroup>
            </Section>
          )}
        </>
      ) : (
        <Section tone="surface" rhythm="tight" aria-label="No posts yet">
          <Reveal className="border-mkt-line rounded-mkt-lg bg-mkt-paper mx-auto max-w-2xl border border-dashed p-12 text-center">
            <span className="border-mkt-line bg-mkt-surface text-mkt-ink-soft mx-auto grid size-12 place-items-center rounded-full border">
              <PenLine aria-hidden strokeWidth={1.8} className="size-5" />
            </span>
            <h2 className="font-mkt-display text-mkt-d4 text-mkt-ink mt-6">
              {BLOG_EMPTY_STATE.heading}
            </h2>
            <p className="text-mkt-body text-mkt-ink-soft mx-auto mt-3 max-w-[80ch]">
              {BLOG_EMPTY_STATE.body}
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <ButtonLink href={DEMO_HREF}>
                {DEMO_CTA}
                <ArrowRight aria-hidden />
              </ButtonLink>
              <ButtonLink href="/faq" intent="secondary">
                Read the FAQ
              </ButtonLink>
            </div>
          </Reveal>
        </Section>
      )}

      <BlogCta
        title="See the product the notes are about."
        secondary={{ href: '/faq', label: 'Read the FAQ' }}
      />
    </>
  );
}

/** First letter of the author name for the avatar tile. */
function authorInitial(author: string) {
  return author.match(/[a-z]/i)?.[0].toUpperCase() ?? '?';
}

/** Date/read-time pair for the post-view byline; omitted while both are absent. */
function PostMetaByline({ post }: Readonly<{ post: BlogPost }>) {
  const parts = [post.date, post.readTime].filter((value): value is string => Boolean(value));
  if (parts.length === 0) return null;
  return <Meta>{parts.join(' · ')}</Meta>;
}

function withOccurrenceKeys<T>(
  values: readonly T[],
  identity: (value: T) => string,
): Array<{ key: string; value: T }> {
  const occurrences = new Map<string, number>();
  return values.map((value) => {
    const base = identity(value);
    const occurrence = occurrences.get(base) ?? 0;
    occurrences.set(base, occurrence + 1);
    return { key: `${base}:${occurrence}`, value };
  });
}

function blockIdentity(block: BlogBlock): string {
  switch (block.type) {
    case 'heading':
    case 'paragraph':
      return `${block.type}:${block.text}`;
    case 'list':
      return `list:${block.items.join('\u001f')}`;
  }
}

function PostBlock({ block }: Readonly<{ block: BlogBlock }>) {
  switch (block.type) {
    case 'heading':
      return <h2 className="font-mkt-display text-mkt-d4 text-mkt-ink mt-10 mb-4">{block.text}</h2>;
    case 'list':
      return (
        <ul className="text-mkt-body text-mkt-ink-soft my-5 grid list-disc gap-2 pl-5">
          {withOccurrenceKeys(block.items, (item) => item).map(({ key, value }) => (
            <li key={key}>{value}</li>
          ))}
        </ul>
      );
    case 'paragraph':
      return <p className="text-mkt-body text-mkt-ink-soft my-5">{block.text}</p>;
  }
}

export function BlogPostView({ post }: Readonly<{ post: BlogPost }>) {
  return (
    <>
      {/* datePublished/author appear only once the owner supplies them (B5). */}
      <JsonLd data={blogPostingJsonLd(post)} />
      <header className="pt-16 pb-10 md:pt-24 md:pb-12">
        <Container>
          <Reveal className="max-w-[90ch]">
            <Link
              href="/blog"
              className="text-mkt-sm text-mkt-ink-muted hover:text-mkt-ink mb-8 inline-flex items-center gap-2 font-semibold transition-colors"
            >
              <ArrowLeft className="size-4" aria-hidden />
              All notes
            </Link>
            <div>
              <Eyebrow>Field notes</Eyebrow>
            </div>
            <TagRow tags={post.tags} />
            <h1 className="font-mkt-display text-mkt-d2 text-mkt-ink mt-4">{post.title}</h1>
            {/* The byline is owner-supplied: the row renders only once at
                least one of author/date/readTime exists. */}
            {(post.author ?? post.date ?? post.readTime) && (
              <div className="border-mkt-line-soft mt-8 flex flex-wrap items-center gap-x-4 gap-y-2 border-t pt-6">
                {post.author && (
                  <span className="text-mkt-sm text-mkt-ink flex items-center gap-3 font-semibold">
                    <span
                      aria-hidden
                      className="bg-mkt-ink text-mkt-surface text-mkt-sm grid size-8 place-items-center rounded-full"
                    >
                      {authorInitial(post.author)}
                    </span>
                    {post.author}
                  </span>
                )}
                <PostMetaByline post={post} />
              </div>
            )}
          </Reveal>
        </Container>
      </header>

      <Container>
        <article aria-label="Post content" className="max-w-[90ch] pb-16">
          <p className="text-mkt-lead text-mkt-ink border-mkt-line border-l-2 pl-5">
            {post.excerpt}
          </p>
          {withOccurrenceKeys(post.body, blockIdentity).map(({ key, value }) => (
            <PostBlock key={key} block={value} />
          ))}
        </article>
      </Container>

      <BlogCta
        title="Make AI visibility measurable."
        secondary={{ href: '/blog', label: 'All posts' }}
      />
    </>
  );
}
