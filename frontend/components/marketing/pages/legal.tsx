import Link from 'next/link';

import {
  FOOTER_LEGAL_LINKS,
  LEGAL_ENTITY,
  type LegalDocument,
} from '@/lib/marketing-content/legal';

import { Meta } from '../primitives/label';
import { Section } from '../primitives/section';
import { Reveal } from '../primitives/reveal';

function formatUpdated(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(date);
}

/**
 * Shared legal document layout — compact header, readable measure, TOC for
 * long policies. Uses the same light semantic tokens as the rest of marketing.
 */
export function LegalDocumentView({ document }: Readonly<{ document: LegalDocument }>) {
  return (
    <main>
      <header className="border-border-subtle border-b pt-16 pb-6 md:pb-8">
        <div className="px-6-phone md:px-6-tablet mx-auto w-full max-w-3xl xl:px-6">
          <Reveal>
            <p className="text-muted text-xs font-semibold tracking-wide uppercase">Legal</p>
            <h1 className="font-display text-foreground mt-3 text-4xl md:text-5xl">
              {document.title}
            </h1>
            <p className="text-muted mt-3 max-w-[60ch] text-base">{document.description}</p>
            <Meta as="p" className="mt-5">
              Last updated · {formatUpdated(LEGAL_ENTITY.lastUpdated)}
            </Meta>
          </Reveal>
        </div>
      </header>

      <Section tone="paper" rhythm="tight" dense>
        <div className="mx-auto grid max-w-3xl gap-10 lg:max-w-5xl lg:grid-cols-[14rem_minmax(0,1fr)] lg:gap-14">
          <nav aria-label="On this page" className="lg:sticky lg:top-24 lg:self-start">
            <p className="text-muted mb-3 text-xs font-semibold tracking-wide uppercase">
              On this page
            </p>
            <ol className="grid gap-2">
              {document.sections.map((section) => (
                <li key={section.id}>
                  <a
                    href={`#${section.id}`}
                    className="text-muted hover:text-foreground text-sm transition-colors"
                  >
                    {section.title}
                  </a>
                </li>
              ))}
            </ol>
          </nav>

          <article className="min-w-0">
            {document.sections.map((section) => (
              <section
                key={section.id}
                id={section.id}
                className="border-border-subtle scroll-mt-28 border-b py-8 last:border-b-0"
              >
                <h2 className="font-display text-foreground text-2xl">{section.title}</h2>
                {section.paragraphs?.map((paragraph, index) => (
                  <p
                    key={`${section.id}-p-${index}`}
                    className="text-muted mt-4 text-base leading-relaxed"
                  >
                    {paragraph}
                  </p>
                ))}
                {section.bullets && section.bullets.length > 0 ? (
                  <ul className="text-muted mt-4 grid list-disc gap-2 pl-5 text-base leading-relaxed">
                    {section.bullets.map((item, index) => (
                      <li key={`${section.id}-b-${index}`}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {section.note ? (
                  <p className="border-border-subtle bg-background-alt text-subtle mt-5 rounded-md border px-4 py-3 text-xs leading-relaxed">
                    {section.note}
                  </p>
                ) : null}
              </section>
            ))}

            <nav
              aria-label="Other legal documents"
              className="border-border-subtle mt-4 flex flex-wrap gap-x-5 gap-y-2 border-t pt-6"
            >
              {FOOTER_LEGAL_LINKS.filter((link) => link.href !== `/${document.slug}`).map(
                (link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="text-accent-text hover:text-accent-hover text-sm font-semibold"
                  >
                    {link.label}
                  </Link>
                ),
              )}
            </nav>
          </article>
        </div>
      </Section>
    </main>
  );
}
