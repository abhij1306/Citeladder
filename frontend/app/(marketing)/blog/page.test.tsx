import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { BlogPostView } from '@/components/marketing/pages/blog';
import type { BlogPost } from '@/lib/marketing-content/blog';
import { BLOG_EMPTY_STATE, POSTS } from '@/lib/marketing-content/blog';
import { DEMO_HREF } from '@/lib/marketing-content/nav';

import BlogPage from './page';

// The typed content module is mocked with a lazy POSTS getter so individual
// tests can swap the posts array (empty state, multi-post grid) while the
// default render keeps the module's real launch post. BLOG_EMPTY_STATE
// and the types pass through from the actual module.
const blogState = vi.hoisted(() => ({
  posts: undefined as readonly BlogPost[] | undefined,
}));
vi.mock('@/lib/marketing-content/blog', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/marketing-content/blog')>();
  return {
    ...actual,
    get POSTS() {
      return blogState.posts ?? actual.POSTS;
    },
  };
});

beforeEach(() => {
  blogState.posts = undefined;
});

describe('Blog index (public marketing `/blog`)', () => {
  it('renders the launch post in the featured slot', () => {
    const { container } = render(<BlogPage />);

    // Exactly one h1; no h2–h6 may contain the product name. Post titles are
    // styled paragraphs carrying role="heading" for assistive tech, so this
    // asserts against literal h2–h6 tags rather than the heading role — the
    // post title is a heading to screen readers but not an h2–h6.
    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(/make AI visibility/i);
    for (const heading of container.querySelectorAll('h2, h3, h4, h5, h6')) {
      expect(heading).not.toHaveTextContent(/citeladder/i);
    }

    const featured = screen.getByRole('region', { name: 'Featured post' });
    expect(within(featured).getByRole('link', { name: POSTS[0].title })).toHaveAttribute(
      'href',
      '/blog/how-we-measure-ai-visibility-deterministically',
    );

    // The empty state is gone now that a real post is live.
    expect(screen.queryByRole('heading', { name: BLOG_EMPTY_STATE.heading })).toBeNull();
    expect(screen.queryByText(BLOG_EMPTY_STATE.body)).toBeNull();
  });

  it('centres the hero like the other marketing subpages', () => {
    render(<BlogPage />);

    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1).toHaveClass('mx-auto');
    expect(h1.closest('.text-center')).not.toBeNull();
  });

  it('maps posts beyond the featured one to the card grid', () => {
    const second: BlogPost = {
      slug: 'second-note',
      title: 'A second note on evidence.',
      excerpt: 'Second excerpt.',
      date: 'Jul 20, 2026',
      readTime: '3 min read',
      author: 'The team',
      tags: ['Field report'],
      body: [],
    };
    blogState.posts = [...POSTS, second];
    render(<BlogPage />);

    const grid = screen.getByRole('region', { name: 'All guides' });
    // Grid carries the second post only — the featured post is not duplicated.
    expect(within(grid).getByRole('link', { name: second.title })).toHaveAttribute(
      'href',
      '/blog/second-note',
    );
    expect(within(grid).queryByRole('link', { name: POSTS[0].title })).toBeNull();
    expect(screen.getByText(/4\s+guides/)).toBeInTheDocument();
  });

  it('renders the empty state when the posts array is empty', () => {
    blogState.posts = [];
    render(<BlogPage />);

    expect(
      screen.getByRole('heading', { level: 2, name: BLOG_EMPTY_STATE.heading }),
    ).toBeInTheDocument();
    expect(screen.getByText(BLOG_EMPTY_STATE.body)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Featured post' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'All guides' })).toBeNull();

    // The page hero (and its single h1) still renders above the empty state.
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
  });
});

describe('BlogPostView (`/blog/[slug]` sync view)', () => {
  it('renders the title, body blocks, and no placeholder chrome', () => {
    const post = POSTS[0];
    const { container } = render(<BlogPostView post={post} />);

    // Single h1 = the post title; back-link returns to the index.
    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(post.title);
    expect(screen.getByRole('link', { name: /all guides/i })).toHaveAttribute('href', '/blog');

    // The excerpt renders as the lede, then one <h2> per heading block and
    // one <ul> per list block, all inside the article.
    const article = screen.getByRole('article', { name: 'Post content' });
    expect(within(article).getByText(post.excerpt)).toBeInTheDocument();
    const headingTexts = post.body.flatMap((block) =>
      block.type === 'heading' ? [block.text] : [],
    );
    expect(headingTexts.length).toBeGreaterThan(0);
    const renderedH2s = within(article).getAllByRole('heading', { level: 2 });
    expect(renderedH2s).toHaveLength(headingTexts.length);
    for (const text of headingTexts) {
      expect(within(article).getByRole('heading', { level: 2, name: text })).toBeInTheDocument();
    }
    const listCount = post.body.filter((block) => block.type === 'list').length;
    const listItems = post.body.flatMap((block) => (block.type === 'list' ? block.items : []));
    if (listCount === 0) {
      expect(within(article).queryAllByRole('list')).toHaveLength(0);
    } else {
      expect(within(article).getAllByRole('list')).toHaveLength(listCount);
      expect(within(article).getAllByRole('listitem')).toHaveLength(listItems.length);
    }

    // No byline row while the owner-supplied fields are absent (B5), and no
    // unfinished placeholder or internal version ids may reach the page.
    const header = container.querySelector('header');
    expect(header?.querySelector('.border-t')).toBeNull();
    expect(container.textContent).not.toMatch(/TODO\(user\)/);
    expect(container.textContent).not.toMatch(
      /scoring-v1|b6-analysis-1|sh-rules-2|opp-formula-1|traffic-formula-1|product-scoring-v2/i,
    );

    // Closing CTA band routes through the stable demo funnel.
    const ctaBand = screen.getByRole('region', { name: 'Get started' });
    expect(within(ctaBand).getByRole('link', { name: /book a demo/i })).toHaveAttribute(
      'href',
      DEMO_HREF,
    );
  });

  it('emits BlogPosting JSON-LD, omitting byline fields until the owner supplies them', () => {
    const post = POSTS[0];
    const { container } = render(<BlogPostView post={post} />);

    const script = container.querySelector('script[type="application/ld+json"]');
    expect(script).not.toBeNull();
    expect(script).not.toHaveAttribute('id');
    const data = JSON.parse(script?.textContent ?? '') as Record<string, unknown>;
    expect(data['@context']).toBe('https://schema.org');
    expect(data['@type']).toBe('BlogPosting');
    expect(data.headline).toBe(post.title);
    expect(data.description).toBe(post.excerpt);
    // B5 unfilled: datePublished/author are omitted, not guessed.
    expect(data).not.toHaveProperty('datePublished');
    expect(data).not.toHaveProperty('author');
  });
});
