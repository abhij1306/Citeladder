import { Plus } from 'lucide-react';
import type { ReactNode } from 'react';

import { FAQ_GROUPS, type FaqGroup } from '@/lib/marketing-content/faq';

import { Meta } from '../primitives/label';
import { Container } from '../primitives/section';

/**
 * FAQ body (`/faq`) — a sticky group rail beside the four question groups.
 *
 * The accordion is native <details>/<summary> on purpose: it keeps the page a
 * sync RSC with zero client JS, and it stays keyboard- and search-accessible
 * without any of the ARIA a hand-rolled accordion would need.
 */
const GROUP_ANCHORS: Record<string, string> = {
  Product: 'faq-product',
  'Privacy & keys': 'faq-privacy',
  'Site health': 'faq-site-health',
  'Account & billing': 'faq-billing',
};

function groupAnchor(group: FaqGroup): string {
  const fallback = group.heading
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return GROUP_ANCHORS[group.heading] ?? `faq-${fallback}`;
}

// Answers are plain strings from the content module. One inline transform
// keeps them faithful: bare URLs render as real links.
const INLINE_TOKEN_RE = /https?:\/\/\S+/g;
// Sentence punctuation straight after a URL belongs to the prose, not the href.
const TRAILING_PUNCT_RE = /[.,;:!?)]+$/;

function AnswerText({ text }: Readonly<{ text: string }>) {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  for (const match of text.matchAll(INLINE_TOKEN_RE)) {
    const token = match[0];
    const start = match.index;
    if (start > cursor) nodes.push(text.slice(cursor, start));
    const trailing = token.match(TRAILING_PUNCT_RE)?.[0] ?? '';
    const href = trailing ? token.slice(0, -trailing.length) : token;
    nodes.push(
      <a
        key={key}
        href={href}
        target="_blank"
        rel="noreferrer"
        className="text-mkt-proof underline underline-offset-2"
      >
        {href}
      </a>,
    );
    key += 1;
    if (trailing) nodes.push(trailing);
    cursor = start + token.length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

export function FaqGroups() {
  return (
    <Container className="grid gap-10 pb-24 lg:grid-cols-[15rem_minmax(0,1fr)] lg:gap-16">
      <nav aria-label="FAQ groups" className="lg:sticky lg:top-28 lg:self-start">
        <Meta as="p" className="mb-4">
          On this page
        </Meta>
        <div className="grid gap-1">
          {FAQ_GROUPS.map((group) => (
            <a
              key={group.heading}
              href={`#${groupAnchor(group)}`}
              className="text-mkt-sm text-mkt-ink-soft hover:bg-mkt-surface hover:text-mkt-ink flex items-center justify-between gap-3 rounded-sm px-3 py-2 transition-colors duration-200"
            >
              {group.heading}
              <span className="text-mkt-ink-muted text-mkt-meta font-mono tabular-nums">
                {group.items.length}
              </span>
            </a>
          ))}
        </div>
      </nav>

      <div className="grid gap-14">
        {FAQ_GROUPS.map((group) => (
          <section key={group.heading} id={groupAnchor(group)} aria-label={group.heading}>
            <div className="border-mkt-line-soft mb-2 flex items-baseline justify-between gap-4 border-b pb-4">
              <h2 className="font-mkt-display text-mkt-d4 text-mkt-ink font-medium">
                {group.heading}
              </h2>
              <Meta>{group.items.length} answers</Meta>
            </div>
            {group.items.map((item) => (
              <details key={item.q} className="border-mkt-line-soft group border-b">
                <summary className="text-mkt-body text-mkt-ink hover:text-mkt-proof flex cursor-pointer list-none items-center justify-between gap-6 py-5 font-semibold transition-colors [&::-webkit-details-marker]:hidden">
                  {item.q}
                  <Plus
                    aria-hidden
                    className="text-mkt-ink-muted size-4 shrink-0 transition-transform duration-300 group-open:rotate-45"
                  />
                </summary>
                <p className="text-mkt-body text-mkt-ink-soft max-w-[70ch] pb-6">
                  <AnswerText text={item.a} />
                </p>
              </details>
            ))}
          </section>
        ))}
      </div>
    </Container>
  );
}
