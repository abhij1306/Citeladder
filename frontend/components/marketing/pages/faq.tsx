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
  Platform: 'faq-platform',
  'Industry packs': 'faq-packs',
  'Data & security': 'faq-security',
  'Account & billing': 'faq-billing',
};

function groupAnchor(group: FaqGroup): string {
  const fallback = group.heading
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-/, '')
    .replace(/-$/, '');
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
        className="text-accent-text underline underline-offset-2"
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
    <Container className="grid gap-10 pb-30 lg:grid-cols-[15rem_minmax(0,1fr)] lg:gap-16">
      <nav aria-label="FAQ groups" className="lg:sticky lg:top-28 lg:self-start">
        <Meta as="p" className="mb-5">
          On this page
        </Meta>
        <div className="grid gap-2">
          {FAQ_GROUPS.map((group) => (
            <a
              key={group.heading}
              href={`#${groupAnchor(group)}`}
              className="text-muted hover:bg-panel hover:text-foreground flex items-center justify-between gap-4 rounded-md px-4 py-3 text-sm transition-colors duration-200"
            >
              {group.heading}
              <span className="text-muted font-mono text-xs tabular-nums">
                {group.items.length}
              </span>
            </a>
          ))}
        </div>
      </nav>

      <div className="grid gap-12">
        {FAQ_GROUPS.map((group) => (
          <section key={group.heading} id={groupAnchor(group)} aria-label={group.heading}>
            <div className="border-border-subtle mb-3 flex items-baseline justify-between gap-5 border-b pb-5">
              <h2 className="website-section-heading text-foreground">{group.heading}</h2>
              <Meta>{group.items.length} answers</Meta>
            </div>
            {group.items.map((item) => (
              <details key={item.q} className="border-border-subtle group border-b">
                <summary className="text-foreground hover:text-accent-text flex cursor-pointer list-none items-center justify-between gap-8 py-5 text-base font-medium transition-colors [&::-webkit-details-marker]:hidden">
                  {item.q}
                  <Plus
                    aria-hidden
                    className="text-muted size-4 shrink-0 transition-transform duration-300 group-open:rotate-45"
                  />
                </summary>
                <p className="website-body-lg text-muted max-w-[75ch] pb-8">
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
