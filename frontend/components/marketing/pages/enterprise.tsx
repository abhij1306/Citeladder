import { ArrowRight, Check, Layers, Shield, Sigma, type LucideIcon } from 'lucide-react';

import { DEMO_HREF } from '@/lib/marketing-content/nav';

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
    icon: Shield,
    title: 'Security & BYOK Privacy',
    tagline: 'Provider credentials stay secret; backend topology never reaches the client bundle.',
    highlights: [
      'Fernet-encrypted BYOK keys at rest',
      'UUID identifiers throughout every workspace',
      'Same-origin API proxying',
    ],
  },
  {
    icon: Sigma,
    title: 'Audit-Ready Evidence',
    tagline: 'Numbers your compliance and security teams can re-derive, not just read.',
    highlights: [
      'Deterministic scoring rules',
      'Immutable artifacts and run logs',
      'No fabricated fallback zeros',
    ],
  },
  {
    icon: Layers,
    title: 'Durable Scale & Reliability',
    tagline: 'Orchestration built to survive worker restarts and heavy job queues.',
    highlights: [
      'PostgreSQL FOR UPDATE SKIP LOCKED queues',
      'Leases, heartbeats & retries',
      'Runtime Zod + Pydantic contracts',
    ],
  },
];

const DATA_FLOW_STEPS = [
  { step: '01', title: 'Browser Client', detail: 'Authenticated HTTPS request' },
  { step: '02', title: 'Next.js Proxy', detail: 'Same-origin edge route' },
  { step: '03', title: 'FastAPI Backend', detail: 'Schema & bearer check' },
  { step: '04', title: 'PostgreSQL', detail: 'Durable queue & runs' },
  { step: '05', title: 'Workers', detail: 'Async task execution' },
  { step: '06', title: 'AI Providers', detail: 'Fernet-encrypted BYOK' },
] as const;

const CUSTOM_LIMITS = [
  {
    title: 'Monthly audit runs',
    badge: 'Custom Volume',
    unit: 'prompt × engine × repetition',
    desc: 'Sized to your volumes for high-concurrency evaluation across all your active brand topics.',
  },
  {
    title: 'Monitored URLs',
    badge: 'Full Brand Set',
    unit: 'total monitored URL set',
    desc: 'The complete set of brand, product, and competitor pages crawled on schedule.',
  },
  {
    title: 'Projects & seats',
    badge: 'Unlimited Teams',
    unit: 'per enterprise workspace',
    desc: 'Each project carries its own prompts, competitors, engines, and evidence trails.',
  },
  {
    title: 'Evidence retention',
    badge: 'Up to 7 Years',
    unit: 'months of compliance history',
    desc: 'Immutable artifacts, raw model responses, and every derived metric preserved.',
  },
  {
    title: 'Engine connections',
    badge: 'All Providers',
    unit: 'OpenAI, Gemini, Claude, Perplexity, DeepSeek',
    desc: 'Connect standard or fine-tuned model endpoints with custom BYOK key routing.',
  },
  {
    title: 'Support & SLA',
    badge: '1-Hour SLA',
    unit: 'guaranteed response window',
    desc: 'Direct Slack/Teams channel, dedicated account manager, and 99.9% uptime target.',
  },
] as const;

export function EnterpriseHero() {
  return (
    <PageHero
      centered
      eyebrow="Enterprise"
      title="AI visibility, with"
      accent="enterprise-grade evidence."
      lead="Platform security teams can verify: deterministic scoring over immutable, provenance-carrying evidence — deployed and operated in our cloud, with the evidence trail your review process needs."
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
        eyebrow="Capabilities"
        title="Built for teams that audit their tools."
        lead="Every claim below maps directly to the running platform architecture — bring your security and compliance team."
        headingId="enterprise-caps-title"
      />

      {/* 3 Spacious Pillar Cards */}
      <StaggerGroup className="grid gap-8 md:grid-cols-3">
        {CAPABILITIES.map(({ icon: Icon, title, tagline, highlights }) => (
          <StaggerItem key={title} className="h-full">
            <div className="bg-background border-border-subtle shadow-card hover:border-accent-border hover:shadow-card-hover flex h-full flex-col justify-between rounded-lg border p-8 transition-all duration-200">
              <div>
                <div className="flex items-center gap-4">
                  <span className="border-accent bg-background-alt text-accent-text grid size-10 shrink-0 place-items-center rounded-md border">
                    <Icon aria-hidden strokeWidth={1.8} className="size-5" />
                  </span>
                  <h3 className="font-display text-foreground text-xl leading-snug">{title}</h3>
                </div>
                <p className="text-muted mt-5 text-base leading-relaxed">{tagline}</p>
              </div>

              <ul className="border-border-subtle mt-8 space-y-4 border-t pt-8">
                {highlights.map((item) => (
                  <li
                    key={item}
                    className="text-foreground flex items-center gap-4 text-sm font-medium"
                  >
                    <Check
                      aria-hidden
                      strokeWidth={2.5}
                      className="text-success-text size-4 shrink-0"
                    />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </StaggerItem>
        ))}
      </StaggerGroup>

      {/* Clean Horizontal Data Flow */}
      <section aria-label="Platform data flow" className="mt-12">
        <div className="mb-5 flex items-center justify-between">
          <p className="text-muted font-mono text-xs uppercase">
            Platform Data Flow & Security Boundaries
          </p>
          <span className="text-accent-text font-mono text-xs uppercase">docs/architecture.md</span>
        </div>
        <Reveal className="bg-background border-border-subtle shadow-card rounded-lg border p-8 md:p-8">
          <div className="grid gap-5 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
            {DATA_FLOW_STEPS.map((s) => (
              <div key={s.step} className="border-border-subtle border-l-2 py-2 pl-5">
                <p className="text-accent-text font-mono text-xs font-semibold">{s.step}</p>
                <p className="text-foreground mt-2 text-base font-semibold">{s.title}</p>
                <p className="text-muted mt-2 text-sm leading-snug">{s.detail}</p>
              </div>
            ))}
          </div>
        </Reveal>
      </section>
    </Section>
  );
}

export function EnterpriseLimits() {
  return (
    <Section id="limits" tone="sunken" rhythm="base" aria-label="Custom limits">
      <SectionHeader
        eyebrow="Custom limits"
        title="Shaped around your requirements."
        lead="Every enterprise agreement starts from these dials — tell us your volumes and we size the plan."
        headingId="enterprise-limits-title"
      />

      {/* Spacious 2-Column Limits Grid */}
      <Reveal className="bg-background border-border-subtle shadow-card overflow-hidden rounded-lg border">
        <div className="border-border-subtle bg-background-alt flex flex-col justify-between gap-5 border-b p-8 md:flex-row md:items-center md:p-8">
          <div>
            <h3 className="font-display text-foreground text-3xl">Tailored Enterprise Sizing</h3>
            <p className="text-muted mt-2 text-base">
              We quote directly against your operational numbers — not arbitrary tier buckets.
            </p>
          </div>
          <span className="border-accent bg-background-alt text-accent-text shrink-0 self-start rounded-md border px-5 py-3 text-sm font-semibold md:self-auto">
            Custom Agreement
          </span>
        </div>

        <StaggerGroup className="bg-background-alt grid gap-px md:grid-cols-2">
          {CUSTOM_LIMITS.map((item) => (
            <StaggerItem
              key={item.title}
              className="bg-background hover:bg-panel p-8 transition-colors"
            >
              <div className="flex flex-wrap items-center justify-between gap-4">
                <h4 className="font-display text-foreground text-xl">{item.title}</h4>
                <span className="border-accent bg-background-alt text-accent-text rounded-md border px-4 py-2 font-mono text-xs uppercase">
                  {item.badge}
                </span>
              </div>
              <p className="text-accent-text mt-3 font-mono text-xs uppercase">{item.unit}</p>
              <p className="text-muted mt-4 text-base leading-relaxed">{item.desc}</p>
            </StaggerItem>
          ))}
        </StaggerGroup>
      </Reveal>

      {/* Bottom Quote CTA Strip */}
      <div className="bg-background border-border-subtle shadow-card mt-8 flex flex-col items-start justify-between gap-8 rounded-lg border p-8 md:flex-row md:items-center">
        <div>
          <p className="font-display text-foreground text-2xl">
            Verifiable Operations & Audit Trail
          </p>
          <p className="text-muted mt-2 max-w-[80ch] text-base leading-relaxed">
            Deterministic scoring rules, immutable run logs, and provenance stamps on every derived
            metric.
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
      <Reveal className="mx-auto max-w-5xl text-center">
        <h2 className="font-display text-foreground mx-auto mb-5 max-w-[32ch] text-4xl">
          Bring AI visibility in-house.
        </h2>
        <p className="text-muted mx-auto max-w-[80ch] text-lg">
          Tell us your volumes, constraints and review process — we’ll shape an enterprise plan
          around them, starting with a walkthrough of your own category.
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
