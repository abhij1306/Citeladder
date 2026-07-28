import { ArrowUpRight } from 'lucide-react';
import Link from 'next/link';

import { COMPETITORS } from '@/lib/marketing-content/compare';
import { DEMO_CTA, DEMO_HREF } from '@/lib/marketing-content/nav';
import { CONTACT_EMAIL, SOCIAL_LINKS, type SocialLink } from '@/lib/marketing-content/social';

import { Container } from '../primitives/section';
import { Meta } from '../primitives/label';
import { Wordmark } from '../primitives/wordmark';

type FooterLink = { label: string; href: string; external?: boolean };
type FooterColumn = { key: string; label: string; links: readonly FooterLink[] };

/**
 * Five columns. Compare maps COMPETITORS from the content module so it stays
 * in sync with /compare; everything else is a static route.
 */
const FOOTER_COLUMNS: readonly FooterColumn[] = [
  {
    key: 'platform',
    label: 'Platform',
    links: [
      { label: 'Market observation', href: '/#platform' },
      { label: 'How it works', href: '/#how-it-works' },
      { label: 'Evidence', href: '/#evidence' },
      { label: 'Pricing', href: '/pricing' },
      { label: 'Enterprise', href: '/enterprise' },
    ],
  },
  {
    key: 'resources',
    label: 'Resources',
    links: [
      { label: 'Blog', href: '/blog' },
      { label: 'FAQ', href: '/faq' },
      { label: 'Compare', href: '/compare' },
    ],
  },
  {
    key: 'solutions',
    label: 'Solutions',
    links: [
      { label: 'Agencies', href: '/solutions#agencies' },
      { label: 'In-house teams', href: '/solutions#in-house' },
      { label: 'Founders', href: '/solutions#founders' },
      { label: 'PR & comms', href: '/solutions#pr' },
    ],
  },
  {
    key: 'compare',
    label: 'Compare',
    links: [
      { label: 'All comparisons', href: '/compare' },
      ...COMPETITORS.map((competitor) => ({
        label: `vs ${competitor.name}`,
        href: `/compare/${competitor.slug}`,
      })),
    ],
  },
  {
    key: 'company',
    label: 'Company',
    links: [
      ...(CONTACT_EMAIL ? [{ label: 'Contact', href: `mailto:${CONTACT_EMAIL}` }] : []),
      { label: DEMO_CTA, href: DEMO_HREF },
      { label: 'Log in', href: '/login' },
    ],
  },
];

const LINK =
  'text-mkt-sm text-mkt-ink-soft hover:text-mkt-ink inline-flex items-center gap-1 transition-colors duration-200';

function FooterColumnLink({ link }: Readonly<{ link: FooterLink }>) {
  if (link.external) {
    return (
      <a className={LINK} href={link.href} target="_blank" rel="noreferrer">
        {link.label}
        <ArrowUpRight className="size-3" aria-hidden />
      </a>
    );
  }
  return link.href.startsWith('/') ? (
    <Link className={LINK} href={link.href}>
      {link.label}
    </Link>
  ) : (
    <a className={LINK} href={link.href}>
      {link.label}
    </a>
  );
}

function SocialButton({ social }: Readonly<{ social: SocialLink }>) {
  const Icon = social.icon;
  const external = social.href !== '#';
  return (
    <a
      href={social.href}
      target={external ? '_blank' : undefined}
      rel={external ? 'noreferrer' : undefined}
      aria-label={social.label}
      className="border-mkt-line bg-mkt-surface text-mkt-ink-soft hover:border-mkt-line-strong grid size-9 place-items-center rounded-sm border transition-colors duration-200"
    >
      <Icon aria-hidden className="size-4" />
    </a>
  );
}

/**
 * MarketingFooter — brand block, five link columns inside the Footer nav
 * landmark, and the legal line. The closing statement stays factual: this is
 * the last thing an enterprise evaluator reads.
 */
export function MarketingFooter() {
  return (
    <footer className="border-mkt-line-soft bg-mkt-surface-sunk border-t">
      <Container className="py-16">
        <nav
          aria-label="Footer"
          className="grid gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-[1.4fr_repeat(5,minmax(0,1fr))]"
        >
          <div className="sm:col-span-2 lg:col-span-1">
            <Link href="/" aria-label="Searchify home">
              <Wordmark />
            </Link>
            <p className="text-mkt-sm text-mkt-ink-soft mt-4 max-w-[26ch]">
              Verifiable AI visibility — every metric opens to the answer it came from.
            </p>
            {SOCIAL_LINKS.length > 0 && (
              <div className="mt-5 flex gap-2">
                {SOCIAL_LINKS.map((social) => (
                  <SocialButton key={social.key} social={social} />
                ))}
              </div>
            )}
          </div>

          {FOOTER_COLUMNS.map((column) => (
            <div key={column.key}>
              <Meta as="p" className="f-col-label mb-4">
                {column.label}
              </Meta>
              <div className="grid justify-items-start gap-2.5">
                {column.links.map((link) => (
                  <FooterColumnLink key={link.label} link={link} />
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-mkt-line-soft mt-12 flex flex-wrap items-center justify-between gap-4 border-t pt-8">
          <Meta>© {new Date().getFullYear()} Searchify · A CUBE27 product</Meta>
          <Meta>Audits run on your own provider keys</Meta>
        </div>
      </Container>
    </footer>
  );
}
