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
  return (
    <Meta as="p" className="mt-5">
      {post.date} · {post.readTime}
    </Meta>
  );
}

function BlogCta({
  title,
  secondary,
}: Readonly<{ title: string; secondary: { href: string; label: string } }>) {
  return (
    <Section divided rhythm="loose" aria-label="Get started">
      <Reveal className="mx-auto max-w-3xl text-center">
        <h2 className="font-mkt-display text-mkt-d2 text-mkt-ink mkt-display-w mx-auto mb-5 max-w-[16ch]">
          {title}
        </h2>
        <p className="text-mkt-lead text-mkt-ink-soft mx-auto max-w-[52ch]">
          Walk through your own category — your prompts, your competitors, and the raw answers
          behind every score.
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-2.5 sm:flex-row">
          <ButtonLink href={DEMO_HREF} className="w-full sm:w-auto">
            {DEMO_CTA}
            <ArrowRight className="size-3.5" aria-hidden />
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
            <Reveal className="border-mkt-line rounded-mkt-xl bg-mkt-surface grid overflow-hidden border lg:grid-cols-[1.2fr_0.8fr]">
              <div className="p-8 md:p-10">
                <TagRow tags={featured.tags} />
                <p
                  role="heading"
                  aria-level={2}
                  className="font-mkt-display text-mkt-d3 text-mkt-ink mkt-display-w max-w-[20ch]"
                >
                  <Link href={`/blog/${featured.slug}`}>{featured.title}</Link>
                </p>
                <p className="text-mkt-body text-mkt-ink-soft mt-4 max-w-[60ch]">
                  {featured.excerpt}
                </p>
                <PostMeta post={featured} />
              </div>
              {/* Cover art is user-supplied per post; the slot stays visibly
                  empty rather than filling with a stock image. */}
              <div className="mkt-wallpaper grid min-h-[14rem] place-items-center p-8">
                <Meta className="border-mkt-glass-line bg-mkt-glass rounded-mkt-pill border border-dashed px-3 py-1.5">
                  Post cover — user supplied
                </Meta>
              </div>
            </Reveal>
          </Section>

          {rest.length > 0 && (
            <Section rhythm="tight" aria-label="All posts">
              <div className="border-mkt-line mb-6 flex items-center justify-between gap-4 border-b pb-4">
                <Meta as="p">All notes</Meta>
                <Meta>
                  {rest.length} {rest.length === 1 ? 'post' : 'posts'}
                </Meta>
              </div>
              <StaggerGroup className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {rest.map((post) => (
                  <StaggerItem
                    key={post.slug}
                    className="border-mkt-line rounded-mkt-lg bg-mkt-surface h-full border p-7"
                  >
                    <TagRow tags={post.tags} />
                    <p
                      role="heading"
                      aria-level={3}
                      className="font-mkt-display text-mkt-ink text-[1.0625rem] font-semibold tracking-[-0.03em]"
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
        <Section rhythm="tight" aria-label="No posts yet">
          <Reveal className="border-mkt-line rounded-mkt-xl bg-mkt-surface mx-auto max-w-2xl border border-dashed p-12 text-center">
            <span className="border-mkt-line bg-mkt-paper text-mkt-ink-soft mx-auto grid size-11 place-items-center rounded-full border">
              <PenLine aria-hidden strokeWidth={1.8} className="size-5" />
            </span>
            <h2 className="font-mkt-display text-mkt-d4 text-mkt-ink mkt-display-w mt-6">
              {BLOG_EMPTY_STATE.heading}
            </h2>
            <p className="text-mkt-body text-mkt-ink-soft mx-auto mt-3 max-w-[52ch]">
              {BLOG_EMPTY_STATE.body}
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-2.5 sm:flex-row">
              <ButtonLink href={DEMO_HREF}>
                {DEMO_CTA}
                <ArrowRight className="size-3.5" aria-hidden />
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

/** First letter of the author name for the avatar tile ('[TODO(user)]' → 'T'). */
function authorInitial(author: string) {
  return author.match(/[a-z]/i)?.[0].toUpperCase() ?? '?';
}

function PostBlock({ block }: Readonly<{ block: BlogBlock }>) {
  switch (block.type) {
    case 'heading':
      return (
        <h2 className="font-mkt-display text-mkt-d4 text-mkt-ink mkt-display-w mt-10 mb-4">
          {block.text}
        </h2>
      );
    case 'list':
      return (
        <ul className="text-mkt-body text-mkt-ink-soft my-5 grid list-disc gap-2 pl-5">
          {/* Keyed by index — items may repeat verbatim (placeholder posts
              are all '[TODO(user)]'). */}
          {block.items.map((item, index) => (
            <li key={index}>{item}</li>
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
      <header className="pt-16 pb-10 md:pt-24 md:pb-12">
        <Container>
          <Reveal className="max-w-[70ch]">
            <Link
              href="/blog"
              className="text-mkt-sm text-mkt-ink-muted hover:text-mkt-ink mb-8 inline-flex items-center gap-2 font-semibold transition-colors"
            >
              <ArrowLeft className="size-3.5" aria-hidden />
              All notes
            </Link>
            <div>
              <Eyebrow>Field notes</Eyebrow>
            </div>
            <TagRow tags={post.tags} />
            <h1 className="font-mkt-display text-mkt-d2 text-mkt-ink mkt-display-w mt-4">
              {post.title}
            </h1>
            <div className="border-mkt-line mt-8 flex flex-wrap items-center gap-x-4 gap-y-2 border-t pt-6">
              <span className="text-mkt-sm text-mkt-ink flex items-center gap-2.5 font-semibold">
                <span
                  aria-hidden
                  className="bg-mkt-ink text-mkt-surface text-mkt-sm grid size-7 place-items-center rounded-full"
                >
                  {authorInitial(post.author)}
                </span>
                {post.author}
              </span>
              <Meta>
                {post.date} · {post.readTime}
              </Meta>
            </div>
          </Reveal>
        </Container>
      </header>

      <Container>
        <article aria-label="Post content" className="max-w-[70ch] pb-16">
          <p className="text-mkt-lead text-mkt-ink border-mkt-line border-l-2 pl-5">
            {post.excerpt}
          </p>
          {post.body.map((block, index) => (
            <PostBlock key={index} block={block} />
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
