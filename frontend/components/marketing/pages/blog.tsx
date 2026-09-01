import { ArrowLeft, ArrowRight, PenLine } from 'lucide-react';
import Link from 'next/link';

import {
  BLOG_EMPTY_STATE,
  POSTS,
  type BlogBlock,
  type BlogPost,
} from '@/lib/marketing-content/blog';
import { DEMO_CTA, DEMO_HREF } from '@/lib/marketing-content/nav';

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
 * Heading rule: index post titles render as paragraphs with role="heading" +
 * aria-level rather than literal h2/h3 — a title may contain "CiteLadder" and
 * no h2–h6 on the marketing surface may. Post view uses real h2s for body
 * headings (those are editorial, not product-name headings).
 */
function TagRow({ tags }: Readonly<{ tags: readonly string[] }>) {
  if (tags.length === 0) return null;
  return (
    <div className="mb-4 flex flex-wrap gap-2">
      {tags.map((tag) => (
        <span
          key={tag}
          className="bg-accent-soft text-accent-text rounded-full px-3 py-1 text-xs font-medium"
        >
          {tag}
        </span>
      ))}
    </div>
  );
}

function PostMeta({ post }: Readonly<{ post: BlogPost }>) {
  const parts = [post.date, post.readTime].filter((value): value is string => Boolean(value));
  if (parts.length === 0) return null;
  return (
    <Meta as="p" className="mt-3">
      {parts.join(' · ')}
    </Meta>
  );
}

function BlogCta({
  title,
  secondary,
}: Readonly<{ title: string; secondary: { href: string; label: string } }>) {
  return (
    <Section tone="sunken" rhythm="base" aria-label="Get started">
      <Reveal className="mx-auto max-w-3xl text-center">
        <h2 className="website-section-heading text-foreground mx-auto mb-3 max-w-[28ch]">
          {title}
        </h2>
        <p className="website-body-lg text-muted mx-auto max-w-[52ch]">
          Build a measurement practice your team can inspect, explain, and improve.
        </p>
        <div className="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
          <ButtonLink href={DEMO_HREF} className="w-full sm:w-auto">
            {DEMO_CTA}
            <ArrowRight aria-hidden />
          </ButtonLink>
          <ButtonLink href={secondary.href} variant="ghost" className="w-full sm:w-auto">
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
        eyebrow="Resources"
        title="Make AI visibility"
        accent="understandable."
        lead="Practical guides for answer-engine optimization, evidence-led measurement, and the work between a finding and the next audit."
      />

      {featured ? (
        <>
          <Section rhythm="tight" aria-label="Featured post">
            <Reveal>
              <Link
                href={`/blog/${featured.slug}`}
                aria-label={featured.title}
                className="bg-panel border-border group hover:border-accent-border block overflow-hidden rounded-2xl border transition-colors duration-200"
              >
                <div className="p-7 md:p-10">
                  <TagRow tags={featured.tags} />
                  <h2 className="website-section-heading text-foreground group-hover:text-accent-text max-w-[32ch] transition-colors duration-200">
                    {featured.title}
                  </h2>
                  <p className="website-body-lg text-muted mt-4 max-w-[65ch]">{featured.excerpt}</p>
                  <PostMeta post={featured} />
                  <span className="text-accent-text mt-5 inline-flex items-center gap-2 text-sm font-medium">
                    Read guide
                    <ArrowRight
                      className="size-4 transition-transform duration-200 group-hover:translate-x-0.5"
                      aria-hidden
                    />
                  </span>
                </div>
              </Link>
            </Reveal>
          </Section>

          {rest.length > 0 && (
            <Section tone="paper" rhythm="tight" aria-label="All guides">
              <div className="mb-5 flex items-center justify-between gap-4">
                <Meta as="p">All guides</Meta>
                <Meta>
                  {rest.length} {rest.length === 1 ? 'guide' : 'guides'}
                </Meta>
              </div>
              <StaggerGroup className="divide-border-subtle bg-panel border-border-subtle divide-y overflow-hidden rounded-2xl border">
                {rest.map((post) => (
                  <StaggerItem key={post.slug}>
                    <Link
                      href={`/blog/${post.slug}`}
                      aria-label={post.title}
                      className="hover:bg-accent-soft group block px-6 py-6 transition-colors duration-200 md:px-8 md:py-7"
                    >
                      <TagRow tags={post.tags} />
                      <h3 className="website-feature-heading text-foreground">{post.title}</h3>
                      <p className="website-body text-muted mt-2 max-w-[65ch]">{post.excerpt}</p>
                      <PostMeta post={post} />
                    </Link>
                  </StaggerItem>
                ))}
              </StaggerGroup>
            </Section>
          )}
        </>
      ) : (
        <Section tone="paper" rhythm="tight" aria-label="No posts yet">
          <Reveal className="border-border-subtle mx-auto max-w-xl rounded-2xl border border-dashed p-10 text-center">
            <span className="bg-accent-soft text-accent-text mx-auto grid size-10 place-items-center rounded-md">
              <PenLine aria-hidden strokeWidth={1.8} className="size-5" />
            </span>
            <h2 className="website-section-heading text-foreground mt-6">
              {BLOG_EMPTY_STATE.heading}
            </h2>
            <p className="website-body text-muted mx-auto mt-3 max-w-[48ch]">
              {BLOG_EMPTY_STATE.body}
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
              <ButtonLink href={DEMO_HREF}>
                {DEMO_CTA}
                <ArrowRight aria-hidden />
              </ButtonLink>
              <ButtonLink href="/faq" variant="ghost">
                Read the FAQ
              </ButtonLink>
            </div>
          </Reveal>
        </Section>
      )}

      <BlogCta
        title="Put these guides into practice."
        secondary={{ href: '/faq', label: 'Read the FAQ' }}
      />
    </>
  );
}

function authorInitial(author: string) {
  return /[a-z]/i.exec(author)?.[0].toUpperCase() ?? '?';
}

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
      return <h2 className="website-feature-heading text-foreground mt-8 mb-3">{block.text}</h2>;
    case 'list':
      return (
        <ul className="website-body text-muted my-4 grid list-disc gap-2 pl-5 leading-relaxed">
          {withOccurrenceKeys(block.items, (item) => item).map(({ key, value }) => (
            <li key={key}>{value}</li>
          ))}
        </ul>
      );
    case 'paragraph':
      return <p className="website-body-lg text-muted my-4">{block.text}</p>;
  }
}

export function BlogPostView({ post }: Readonly<{ post: BlogPost }>) {
  return (
    <>
      <JsonLd
        data={{
          ...blogPostingJsonLd(post),
          articleSection: post.tags,
          keywords: post.tags,
        }}
      />
      <header className="border-border-subtle border-b pt-16 pb-6 md:pb-8">
        <Container dense>
          <Reveal className="mx-auto w-full max-w-3xl">
            <Link
              href="/blog"
              className="text-muted hover:text-foreground mb-5 flex w-fit items-center gap-2 text-sm font-medium transition-colors"
            >
              <ArrowLeft className="size-4" aria-hidden />
              All guides
            </Link>
            <Eyebrow>Guide</Eyebrow>
            <TagRow tags={post.tags} />
            <h1 className="website-page-title text-foreground mt-3 max-w-[28ch] text-balance">
              {post.title}
            </h1>
            {(post.author ?? post.date ?? post.readTime) && (
              <div className="border-border-subtle mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 border-t pt-5">
                {post.author && (
                  <span className="text-foreground flex items-center gap-3 text-sm font-medium">
                    <span
                      aria-hidden
                      className="bg-accent-soft text-accent-text grid size-7 place-items-center rounded-md text-xs font-medium"
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

      <Container dense>
        <article aria-label="Post content" className="mx-auto w-full max-w-3xl py-8 md:py-10">
          <p className="website-body-lg bg-accent-soft text-foreground mb-6 rounded-lg px-5 py-4 font-medium">
            {post.excerpt}
          </p>
          {withOccurrenceKeys(post.body, blockIdentity).map(({ key, value }) => (
            <PostBlock key={key} block={value} />
          ))}
        </article>
      </Container>

      <BlogCta
        title="Make AI visibility measurable."
        secondary={{ href: '/blog', label: 'All guides' }}
      />
    </>
  );
}
