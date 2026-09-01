import type { BlogPost } from '@/lib/marketing-content/blog';
import type { FaqGroup } from '@/lib/marketing-content/faq';
import { absoluteUrl, SITE_NAME, SITE_TAGLINE } from '@/lib/seo/site';

export type JsonLdObject = Record<string, unknown>;

export function organizationJsonLd(): JsonLdObject | null {
  const url = absoluteUrl('/');
  if (!url) return null;
  return {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    name: SITE_NAME,
    description: SITE_TAGLINE,
    url,
  };
}

export function websiteJsonLd(): JsonLdObject | null {
  const url = absoluteUrl('/');
  if (!url) return null;
  return {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: SITE_NAME,
    description: SITE_TAGLINE,
    url,
    publisher: { '@type': 'Organization', name: SITE_NAME, url },
  };
}

export function faqPageJsonLd(groups: readonly FaqGroup[]): JsonLdObject {
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: groups.flatMap((group) =>
      group.items.map((item) => ({
        '@type': 'Question',
        name: item.q,
        acceptedAnswer: { '@type': 'Answer', text: item.a },
      })),
    ),
  };
}

export function blogPostingJsonLd(post: BlogPost): JsonLdObject {
  const url = absoluteUrl(`/blog/${post.slug}`);
  const organizationUrl = absoluteUrl('/');
  return {
    '@context': 'https://schema.org',
    '@type': 'BlogPosting',
    headline: post.title,
    description: post.excerpt,
    ...(url ? { url, mainEntityOfPage: { '@type': 'WebPage', '@id': url } } : {}),
    ...(organizationUrl
      ? { publisher: { '@type': 'Organization', name: SITE_NAME, url: organizationUrl } }
      : {}),
    ...(post.date ? { datePublished: post.date } : {}),
    ...(post.author ? { author: { '@type': 'Person', name: post.author } } : {}),
  };
}

/** Prevent a JSON value from terminating its containing script element. */
export function serializeJsonLd(data: JsonLdObject): string {
  return JSON.stringify(data).replace(/</g, '\\u003c');
}
