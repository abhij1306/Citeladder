/**
 * Sanitised Markdown renderer for AI-generated content (Content vertical).
 *
 * The model output is UNTRUSTED. Defences, all local to this module:
 *   - raw HTML is never parsed (no `rehype-raw`; react-markdown escapes it),
 *   - URLs pass `safeUrlTransform` (./safe-url) — only http/https/mailto survive
 *     (`javascript:`/`data:`/etc. are neutralised to an empty href),
 *   - links open in a new tab with `rel="noopener noreferrer"`,
 *   - a restricted component map (no images, no iframes) with token-only
 *     classes so the output inherits the app theme.
 */
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { cn } from '@/lib/utils';

import { safeUrlTransform } from './safe-url';

/** Render untrusted Markdown safely (GFM tables/lists, no raw HTML). */
export function ContentMarkdown({
  markdown,
  density = 'default',
}: Readonly<{ markdown: string; density?: 'default' | 'compact' }>) {
  const content = markdown ?? '';
  return (
    // Generated Markdown can contain unbreakable URLs, code, and wide tables.
    // Keep those inside the reading surface instead of creating one document-
    // wide scrollbar that is reachable only at the bottom of a long result.
    <div
      className={cn(
        'text-foreground [&_h1]:font-display [&_h1]:text-foreground [&_h2]:font-display [&_h2]:text-foreground [&_h3]:font-display [&_h3]:text-foreground [&_p]:text-foreground/90 [&_a]:text-accent-text hover:[&_a]:text-accent-hover [&_blockquote]:border-accent [&_blockquote]:bg-accent-subtle/40 [&_blockquote]:text-secondary [&_code]:bg-well [&_code]:border-border/60 [&_pre]:bg-well [&_pre]:border-border/80 [&_th]:border-border [&_th]:bg-well [&_td]:border-border min-w-0 w-full max-w-full overflow-hidden [overflow-wrap:anywhere] [&_a]:underline [&_a]:underline-offset-2 [&_blockquote]:rounded-r-sm [&_blockquote]:border-l-4 [&_blockquote]:italic [&_code]:rounded-xs [&_code]:border [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-xs [&_h1]:font-semibold [&_h1]:tracking-tight [&_h2]:font-semibold [&_h2]:tracking-tight [&_h3]:font-semibold [&_h3]:tracking-tight [&_li]:leading-relaxed [&_ol]:ml-6 [&_ol]:list-decimal [&_pre]:max-w-full [&_pre]:whitespace-pre-wrap [&_pre]:rounded-sm [&_pre]:border [&_pre]:font-mono [&_pre_code]:border-0 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_table]:w-full [&_table]:table-fixed [&_table]:border-collapse [&_table]:text-sm [&_td]:border [&_th]:border [&_th]:text-left [&_th]:font-semibold [&_ul]:ml-6 [&_ul]:list-disc',
        density === 'compact'
          ? 'text-sm leading-relaxed [&_blockquote]:my-3 [&_blockquote]:py-2 [&_blockquote]:pl-3 [&_h1]:mt-4 [&_h1]:mb-2 [&_h1]:text-lg [&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:text-base [&_h3]:mt-3 [&_h3]:mb-1.5 [&_h3]:text-sm [&_ol]:mb-3 [&_ol]:space-y-1.5 [&_p]:mb-3 [&_p]:leading-relaxed [&_pre]:my-3 [&_pre]:p-3 [&_pre]:text-xs [&_table]:my-3 [&_td]:px-3 [&_td]:py-2 [&_th]:px-3 [&_th]:py-2 [&_ul]:mb-3 [&_ul]:space-y-1.5'
          : 'text-base leading-relaxed [&_blockquote]:my-4 [&_blockquote]:py-2.5 [&_blockquote]:pl-4 [&_h1]:mt-6 [&_h1]:mb-3 [&_h1]:text-2xl [&_h2]:mt-6 [&_h2]:mb-3 [&_h2]:text-xl [&_h3]:mt-5 [&_h3]:mb-2 [&_h3]:text-base [&_ol]:mb-4 [&_ol]:space-y-2 [&_p]:mb-4 [&_p]:leading-relaxed [&_pre]:my-5 [&_pre]:p-4 [&_pre]:text-sm [&_table]:my-5 [&_td]:px-4 [&_td]:py-2.5 [&_th]:px-4 [&_th]:py-2.5 [&_ul]:mb-4 [&_ul]:space-y-2',
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={safeUrlTransform}
        components={{
          // Untrusted output: never render images (remote-fetch beacon risk).
          img: () => null,
          // Forward the remaining DOM props (id, aria-describedby,
          // data-footnote-*) so GFM footnote back-links keep working; `node`
          // is react-markdown's AST handle, not a DOM attribute.
          a: ({ node: _node, children, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
