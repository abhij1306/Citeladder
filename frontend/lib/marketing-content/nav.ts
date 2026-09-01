/**
 * Navigation content for the marketing chrome (desktop dropdowns + the mobile
 * accordions, which render the same tree). Anchors are absolute (`/#see-it`)
 * so every row resolves from a subpage, not just from `/`.
 */
export type NavDropKey = 'platform' | 'solutions' | 'resources';

export type NavDropItem =
  | { title: string; desc: string; href: string; external?: boolean }
  | { num: string; title: string; desc: string; href: string };

type NavDropGroup = { label?: string; items: readonly NavDropItem[] };

export type NavDrop = {
  key: NavDropKey;
  label: string;
  href: string;
  groups: readonly NavDropGroup[];
};

export const NAV_DROPS: readonly NavDrop[] = [
  {
    key: 'platform',
    label: 'Platform',
    href: '/#see-it',
    groups: [
      {
        items: [
          {
            title: 'See it',
            desc: 'The whole system in one workspace',
            href: '/#see-it',
          },
          {
            title: 'How it works',
            desc: 'Collect, analyze, improve, verify',
            href: '/#how-it-works',
          },
          {
            title: 'Use cases',
            desc: 'Workflows for different business models',
            href: '/#use-cases',
          },
          {
            title: 'Evidence and privacy',
            desc: 'Inspectable evidence with isolated data',
            href: '/#trust',
          },
        ],
      },
    ],
  },
  {
    key: 'solutions',
    label: 'Solutions',
    href: '/solutions',
    groups: [
      {
        items: [
          {
            title: 'Agencies',
            desc: 'Audits for every client workspace',
            href: '/solutions#agencies',
          },
          {
            title: 'In-house teams',
            desc: 'AI answers beside your rankings',
            href: '/solutions#in-house',
          },
          { title: 'Founders', desc: 'See if engines recommend you', href: '/solutions#founders' },
          {
            title: 'Ecommerce',
            desc: 'Product share of voice and price accuracy',
            href: '/solutions#commerce',
          },
          {
            title: 'PR & comms',
            desc: 'See what engines say after a launch',
            href: '/solutions#pr',
          },
        ],
      },
    ],
  },
  {
    key: 'resources',
    label: 'Resources',
    href: '/blog',
    groups: [
      {
        items: [
          {
            title: 'Blog',
            desc: 'Practical guides to AI visibility and site evidence',
            href: '/blog',
          },
          { title: 'FAQ', desc: 'Answers on AEO, evidence, security, and billing', href: '/faq' },
          {
            title: 'Compare',
            desc: 'Evidence-led notes on AI visibility platforms',
            href: '/compare',
          },
        ],
      },
    ],
  },
];

/** Plain links that sit after the dropdown triggers. */
export const NAV_LINKS = [
  { label: 'Enterprise', href: '/enterprise' },
  { label: 'Pricing', href: '/pricing' },
] as const;

/**
 * The demo-first funnel. Every primary CTA on the surface points here — the
 * enterprise page owns the contact affordance (and its mailto fallback), so
 * there is exactly one place to change when a real demo form exists.
 */
export const DEMO_HREF = '/demo';
export const DEMO_CTA = 'Book a demo';
