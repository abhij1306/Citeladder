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
      <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
        <ButtonLink href={DEMO_HREF}>
          Book a demo
          <ArrowRight aria-hidden />
        </ButtonLink>
        <ButtonLink href="/pricing" intent="secondary">
          Compare plans
        </ButtonLink>
      </div>
      <TrustStrip className="mt-8 justify-center" />
    </PageHero>
  );
}

export function EnterpriseOps() {
  return (
    <Section id="capabilities" tone="surface" rhythm="loose" aria-label="Enterprise capabilities">
      <SectionHeader
        kicker="Capabilities"
        title="Built for teams that audit their tools."
        intro="Every claim below maps directly to the running platform architecture — bring your security and compliance team."
        headingId="enterprise-caps-title"
      />

      {/* 3 Spacious Pillar Cards */}
      <StaggerGroup className="grid gap-6 md:grid-cols-3">
        {CAPABILITIES.map(({ icon: Icon, title, tagline, highlights }) => (
          <StaggerItem key={title} className="h-full">
            <div className="rounded-mkt-lg bg-mkt-paper border-mkt-line hover:border-mkt-proof/40 shadow-card flex h-full flex-col justify-between border p-8 transition-all duration-200">
              <div>
                <div className="flex items-center gap-3">
                  <span className="border-mkt-proof-line bg-mkt-wash text-mkt-proof grid size-10 shrink-0 place-items-center rounded-md border">
                    <Icon aria-hidden strokeWidth={1.8} className="size-5" />
                  </span>
                  <h3 className="font-mkt-display text-mkt-d4 text-mkt-ink leading-snug">
                    {title}
                  </h3>
                </div>
                <p className="text-mkt-body text-mkt-ink-soft mt-4 leading-relaxed">{tagline}</p>
              </div>

              <ul className="border-mkt-line-soft mt-8 space-y-3 border-t pt-6">
                {highlights.map((item) => (
                  <li
                    key={item}
                    className="text-mkt-sm text-mkt-ink flex items-center gap-3 font-medium"
                  >
                    <Check
                      aria-hidden
                      strokeWidth={2.5}
                      className="text-mkt-evidence-text size-4 shrink-0"
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
        <div className="mb-4 flex items-center justify-between">
          <p className="text-mkt-meta text-mkt-ink-muted font-mono uppercase">
            Platform Data Flow & Security Boundaries
          </p>
          <span className="text-mkt-meta text-mkt-proof font-mono uppercase">
            docs/architecture.md
          </span>
        </div>
        <Reveal className="rounded-mkt-lg bg-mkt-paper border-mkt-line shadow-card border p-6 md:p-8">
          <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
            {DATA_FLOW_STEPS.map((s) => (
              <div key={s.step} className="border-mkt-line-soft border-l-2 py-1 pl-4">
                <p className="text-mkt-meta text-mkt-proof font-mono font-bold">{s.step}</p>
                <p className="text-mkt-body text-mkt-ink mt-1 font-semibold">{s.title}</p>
                <p className="text-mkt-sm text-mkt-ink-muted mt-1 leading-snug">{s.detail}</p>
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
    <Section id="limits" tone="sunken" rhythm="loose" aria-label="Custom limits">
      <SectionHeader
        kicker="Custom limits"
        title="Shaped around your requirements."
        intro="Every enterprise agreement starts from these dials — tell us your volumes and we size the plan."
        headingId="enterprise-limits-title"
      />

      {/* Spacious 2-Column Limits Grid */}
      <Reveal className="rounded-mkt-lg bg-mkt-paper border-mkt-line shadow-card overflow-hidden border">
        <div className="border-mkt-line-soft bg-mkt-wash/30 flex flex-col justify-between gap-4 border-b p-6 md:flex-row md:items-center md:p-8">
          <div>
            <h3 className="font-mkt-display text-mkt-d3 text-mkt-ink">
              Tailored Enterprise Sizing
            </h3>
            <p className="text-mkt-body text-mkt-ink-soft mt-1">
              We quote directly against your operational numbers — not arbitrary tier buckets.
            </p>
          </div>
          <span className="border-mkt-proof-line bg-mkt-wash text-mkt-proof text-mkt-sm shrink-0 self-start rounded-sm border px-4 py-2 font-semibold md:self-auto">
            Custom Agreement
          </span>
        </div>

        <StaggerGroup className="bg-mkt-line-soft grid gap-px md:grid-cols-2">
          {CUSTOM_LIMITS.map((item) => (
            <StaggerItem
              key={item.title}
              className="bg-mkt-paper hover:bg-mkt-surface p-8 transition-colors"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h4 className="font-mkt-display text-mkt-d4 text-mkt-ink">{item.title}</h4>
                <span className="border-mkt-proof-line bg-mkt-wash text-mkt-proof text-mkt-meta rounded-sm border px-3 py-1 font-mono uppercase">
                  {item.badge}
                </span>
              </div>
              <p className="text-mkt-meta text-mkt-proof mt-2 font-mono uppercase">{item.unit}</p>
              <p className="text-mkt-body text-mkt-ink-soft mt-3 leading-relaxed">{item.desc}</p>
            </StaggerItem>
          ))}
        </StaggerGroup>
      </Reveal>

      {/* Bottom Quote CTA Strip */}
      <div className="rounded-mkt-lg bg-mkt-paper shadow-card border-mkt-line mt-8 flex flex-col items-start justify-between gap-6 border p-8 md:flex-row md:items-center">
        <div>
          <p className="font-mkt-display text-mkt-d4 text-mkt-ink">
            Verifiable Operations & Audit Trail
          </p>
          <p className="text-mkt-body text-mkt-ink-soft mt-1 max-w-[80ch] leading-relaxed">
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
    <Section id="contact" tone="field" rhythm="loose" aria-label="Contact sales">
      <Reveal className="mx-auto max-w-5xl text-center">
        <h2 className="font-mkt-display text-mkt-d2 text-mkt-ink mx-auto mb-5 max-w-[32ch]">
          Bring AI visibility in-house.
        </h2>
        <p className="text-mkt-lead text-mkt-ink-soft mx-auto max-w-[80ch]">
          Tell us your volumes, constraints and review process — we’ll shape an enterprise plan
          around them, starting with a walkthrough of your own category.
        </p>
        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <ButtonLink href={DEMO_HREF} className="w-full sm:w-auto">
            Book a demo
            <ArrowRight aria-hidden />
          </ButtonLink>
          <ButtonLink href="/faq" intent="secondary" className="w-full sm:w-auto">
            Read the FAQ
          </ButtonLink>
        </div>
        <TrustStrip className="mt-8 justify-center" />
      </Reveal>
    </Section>
  );
}
