import { ArrowRight, Check, KeyRound, Scale, ShieldCheck, type LucideIcon } from 'lucide-react';

import { DEMO_HREF } from '@/lib/marketing-content/nav';
import { cn } from '@/lib/utils';

import { ButtonLink } from '../primitives/button';
import { PageHero } from '../primitives/page-hero';
import { Section, SectionHeader } from '../primitives/section';
import { Reveal, StaggerGroup, StaggerItem } from '../primitives/reveal';
import { TrustStrip } from '../primitives/trust-strip';

type Capability = {
  icon: LucideIcon;
  title: string;
  tagline: string;
  highlights: readonly string[];
};

const CAPABILITIES: readonly Capability[] = [
  {
    icon: KeyRound,
    title: 'Keys stay yours',
    tagline: 'BYOK credentials never leave your control path.',
    highlights: [
      'Fernet-encrypted BYOK keys at rest',
      'UUID identifiers throughout every workspace',
      'Same-origin API proxying — backend topology never reaches the client bundle',
    ],
  },
  {
    icon: Scale,
    title: 'Evidence you can re-derive',
    tagline: 'Compliance reads the same number your team does.',
    highlights: [
      'Deterministic scoring rules',
      'Immutable artifacts and run logs',
      'No fabricated fallback zeros',
    ],
  },
  {
    icon: ShieldCheck,
    title: 'Built to keep running',
    tagline: 'Queue durability under load, not best-effort jobs.',
    highlights: [
      'PostgreSQL FOR UPDATE SKIP LOCKED queues',
      'Leases, heartbeats & retries',
      'Runtime Zod + Pydantic contracts',
    ],
  },
];

const DATA_FLOW_STEPS = [
  { title: 'Browser', detail: 'Authenticated HTTPS' },
  { title: 'Edge proxy', detail: 'Same-origin Next.js' },
  { title: 'API', detail: 'Schema + workspace auth' },
  { title: 'PostgreSQL', detail: 'Durable queue & runs' },
  { title: 'Workers', detail: 'Leased execution' },
  { title: 'Providers', detail: 'BYOK at execution time' },
] as const;

const CUSTOM_LIMITS = [
  {
    title: 'Monthly audit runs',
    badge: 'Volume',
    unit: 'prompt × engine × repetition',
    desc: 'Sized to concurrent evaluation across your active brand topics.',
  },
  {
    title: 'Monitored URLs',
    badge: 'Coverage',
    unit: 'total monitored URL set',
    desc: 'Brand, product and competitor pages included in your site-health scope.',
  },
  {
    title: 'Projects & seats',
    badge: 'Teams',
    unit: 'per enterprise workspace',
    desc: 'Each project keeps its own prompts, competitors, engines and trails.',
  },
  {
    title: 'Evidence retention',
    badge: 'History',
    unit: 'set by agreement',
    desc: 'Retention terms for raw responses, artifacts and derived metrics.',
  },
  {
    title: 'Engine connections',
    badge: 'Providers',
    unit: 'OpenAI, Google, Anthropic',
    desc: 'The supported direct transports, each using workspace BYOK credentials.',
  },
  {
    title: 'Support & SLA',
    badge: 'Response',
    unit: 'set by agreement',
    desc: 'Response commitments and support channels defined in the contract.',
  },
] as const;

export function EnterpriseHero() {
  return (
    <PageHero
      centered
      eyebrow="Enterprise"
      title="AI visibility, with"
      accent="enterprise-grade evidence."
      lead="Deterministic scores over immutable provenance — operated in our cloud, ready for your security review."
    >
      <div className="mt-8 flex flex-col justify-center gap-4 sm:flex-row">
        <ButtonLink href={DEMO_HREF}>
          Book a demo
          <ArrowRight aria-hidden />
        </ButtonLink>
        <ButtonLink href="/pricing" variant="ghost">
          Compare plans
        </ButtonLink>
      </div>
      <TrustStrip className="mt-8 justify-center" />
    </PageHero>
  );
}

export function EnterpriseOps() {
  return (
    <Section id="capabilities" tone="paper" rhythm="base" aria-label="Enterprise capabilities">
      <SectionHeader
        eyebrow="Trust"
        title="What security and compliance need to see."
        lead="Three guarantees. No marketing fog — each maps to running architecture."
        headingId="enterprise-caps-title"
      />

      <StaggerGroup className="grid gap-5 md:grid-cols-3">
        {CAPABILITIES.map(({ icon: Icon, title, tagline, highlights }) => (
          <StaggerItem key={title} className="h-full">
            <article className="border-border-subtle bg-panel shadow-card hover:shadow-card-hover flex h-full flex-col rounded-lg border p-7 transition-[box-shadow] duration-200">
              <div className="bg-accent-soft text-accent-text grid size-10 place-items-center rounded-md">
                <Icon aria-hidden strokeWidth={1.8} className="size-5" />
              </div>
              <h3 className="font-display text-foreground mt-5 text-xl leading-snug">{title}</h3>
              <p className="text-muted mt-3 text-sm leading-relaxed">{tagline}</p>
              <ul className="border-border-subtle mt-6 space-y-3 border-t pt-6">
                {highlights.map((item) => (
                  <li key={item} className="text-foreground flex gap-3 text-sm">
                    <Check
                      aria-hidden
                      strokeWidth={2.5}
                      className="text-success-text mt-0.5 size-4 shrink-0"
                    />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </article>
          </StaggerItem>
        ))}
      </StaggerGroup>

      <section aria-label="Platform data flow" className="mt-12">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <p className="text-muted text-sm font-semibold">How a request travels</p>
          <span className="text-subtle text-xs">Managed cloud · same-origin boundary</span>
        </div>
        <Reveal className="border-border-subtle bg-panel shadow-card overflow-hidden rounded-lg border">
          <ol className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            {DATA_FLOW_STEPS.map((step, index) => (
              <li
                key={step.title}
                className={cn(
                  'relative flex flex-col gap-2 p-5',
                  index < DATA_FLOW_STEPS.length - 1 &&
                    'border-border-subtle max-xl:border-b xl:border-r',
                )}
              >
                <span className="text-accent-text text-xs font-semibold tabular-nums">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <p className="text-foreground text-sm font-semibold">{step.title}</p>
                <p className="text-muted text-xs leading-snug">{step.detail}</p>
              </li>
            ))}
          </ol>
        </Reveal>
      </section>
    </Section>
  );
}

export function EnterpriseLimits() {
  return (
    <Section id="limits" tone="sunken" rhythm="base" aria-label="Custom limits">
      <SectionHeader
        eyebrow="Sizing"
        title="Dials, not buckets."
        lead="We quote against your volumes — not a fixed tier sheet."
        headingId="enterprise-limits-title"
      />

      <Reveal className="border-border-subtle bg-panel shadow-card overflow-hidden rounded-lg border">
        <div className="border-border-subtle bg-accent-soft flex flex-col justify-between gap-4 border-b px-6 py-5 md:flex-row md:items-center md:px-8">
          <div>
            <h3 className="font-display text-foreground text-2xl">Enterprise agreement</h3>
            <p className="text-muted mt-1 text-sm">Six dials. One quote.</p>
          </div>
          <span className="border-accent-border bg-panel text-accent-text shrink-0 rounded-md border px-4 py-2 text-xs font-semibold tracking-wide uppercase">
            Quoted to fit
          </span>
        </div>

        <StaggerGroup className="bg-background-alt grid gap-px md:grid-cols-2 xl:grid-cols-3">
          {CUSTOM_LIMITS.map((item) => (
            <StaggerItem
              key={item.title}
              className="bg-panel hover:bg-accent-soft p-6 transition-colors duration-200 md:p-7"
            >
              <div className="flex items-start justify-between gap-3">
                <h4 className="font-display text-foreground text-lg">{item.title}</h4>
                <span className="bg-well text-secondary shrink-0 rounded-md px-2.5 py-1 text-xs font-semibold">
                  {item.badge}
                </span>
              </div>
              <p className="text-accent-text mt-3 text-xs font-semibold">{item.unit}</p>
              <p className="text-muted mt-2 text-sm leading-relaxed">{item.desc}</p>
            </StaggerItem>
          ))}
        </StaggerGroup>
      </Reveal>

      <div className="border-border-subtle bg-panel shadow-card mt-8 flex flex-col items-start justify-between gap-6 rounded-lg border p-6 md:flex-row md:items-center md:p-8">
        <div>
          <p className="font-display text-foreground text-2xl">Audit trail included</p>
          <p className="text-muted mt-2 max-w-[60ch] text-sm leading-relaxed">
            Deterministic rules, immutable logs, provenance on every derived metric.
          </p>
        </div>
        <ButtonLink href={DEMO_HREF} className="shrink-0">
          Request custom quote
          <ArrowRight aria-hidden />
        </ButtonLink>
      </div>
    </Section>
  );
}

export function EnterpriseContactCta() {
  return (
    <Section id="contact" tone="paper" rhythm="base" aria-label="Contact sales">
      <Reveal className="mx-auto max-w-3xl text-center">
        <h2 className="font-display text-foreground mx-auto mb-4 max-w-[28ch] text-4xl">
          Bring AI visibility in-house.
        </h2>
        <p className="text-muted mx-auto max-w-[56ch] text-lg">
          Volumes, constraints, review process — we shape the plan around them.
        </p>
        <div className="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
          <ButtonLink href={DEMO_HREF} className="w-full sm:w-auto">
            Book a demo
            <ArrowRight aria-hidden />
          </ButtonLink>
          <ButtonLink href="/faq" variant="ghost" className="w-full sm:w-auto">
            Read the FAQ
          </ButtonLink>
        </div>
        <TrustStrip className="mt-8 justify-center" />
      </Reveal>
    </Section>
  );
}
