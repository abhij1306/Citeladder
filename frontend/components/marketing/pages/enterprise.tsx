import { ArrowRight, Check, Layers, Shield, Sigma, type LucideIcon } from 'lucide-react';
import { Fragment } from 'react';

import { DEMO_HREF } from '@/lib/marketing-content/nav';

import { ButtonLink } from '../primitives/button';
import { Meta } from '../primitives/label';
import { PageHero } from '../primitives/page-hero';
import { Section, SectionHeader } from '../primitives/section';
import { Reveal, StaggerGroup, StaggerItem } from '../primitives/reveal';
import { TrustStrip } from '../primitives/trust-strip';

/**
 * `/enterprise` explains the offer; every sales action uses the stable `/demo`
 * funnel through the centralized `DEMO_HREF`.
 */
type Capability = { icon: LucideIcon; title: string; blurb: string; points: readonly string[] };

/**
 * Every claim here maps to something in the running platform (README's
 * "Built for trustworthy operations", docs/architecture.md). No certification
 * or compliance claims — nothing the repository cannot ground.
 */
const OPS_CARDS: readonly Capability[] = [
  {
    icon: Shield,
    title: 'Security & privacy',
    blurb: 'Provider credentials stay secret, and backend topology stays server-side.',
    points: [
      'Strict workspace isolation — UUID identifiers throughout',
      'BYOK keys Fernet-encrypted at rest, write-only after save',
      'Same-origin API proxying — backend topology never reaches the client bundle',
    ],
  },
  {
    icon: Sigma,
    title: 'Audit-ready evidence',
    blurb: 'Numbers your compliance team can re-derive, not just read.',
    points: [
      'Deterministic scoring — analyzer + rule versions on every projection',
      'Immutable artifacts + provenance-carrying analyses, written once',
      'Unsupported metrics render as —, never fabricated zeros',
    ],
  },
  {
    icon: Layers,
    title: 'Scale & reliability',
    blurb: 'Orchestration that survives worker restarts and Monday-morning queues.',
    points: [
      'PostgreSQL durable queues — FOR UPDATE SKIP LOCKED, no Redis dependency',
      'Leases, heartbeats, retries and idempotency on every task',
      'Custom audit + crawl volumes tailored to your team',
    ],
  },
  {
    icon: Sigma,
    title: 'Traceable by design',
    blurb: 'Every derived number carries the version of the code that produced it.',
    points: [
      'Provenance stamps on every projection — scoring-v1, sh-rules-2, opp-formula-1',
      'Immutable artifacts — a score is recomputable from the persisted run',
      'Typed contracts validated at runtime — Zod + Pydantic',
    ],
  },
];

/** Platform data flow (grounded in docs/architecture.md). */
const ARCH_FLOW = [
  { node: 'Browser', arrow: '→' },
  { node: 'Next.js same-origin proxy', arrow: '→' },
  { node: 'FastAPI', arrow: '→' },
  { node: 'PostgreSQL', arrow: '⇄' },
  { node: 'Workers', arrow: '→' },
] as const;

/** The dials an enterprise agreement is sized on. Values are per-agreement. */
const LIMIT_CELLS = [
  { label: 'Monthly audit runs', desc: 'prompt × engine × repetition, aggregated across projects' },
  { label: 'Monitored URLs', desc: 'total monitored set across all projects' },
  { label: 'Projects', desc: 'per workspace, each with its own prompts + competitors' },
  { label: 'Seats', desc: 'workspace members with access to audits + evidence' },
  { label: 'Evidence retention', desc: 'immutable artifacts, runs and derived projections' },
  { label: 'Support & SLA', desc: 'response targets, channels and escalation path' },
] as const;

function CheckList({ points }: Readonly<{ points: readonly string[] }>) {
  return (
    <ul className="mt-5 grid gap-2.5">
      {points.map((point) => (
        <li key={point} className="text-mkt-sm text-mkt-ink-soft flex gap-3">
          <Check
            aria-hidden
            strokeWidth={2.5}
            className="text-mkt-evidence-text mt-0.5 size-3.5 shrink-0"
          />
          {point}
        </li>
      ))}
    </ul>
  );
}

function CapabilityCard({ icon: Icon, title, blurb, points }: Capability) {
  return (
    <div className="rounded-mkt-lg bg-mkt-surface shadow-card h-full p-7">
      <span className="border-mkt-proof-line bg-mkt-wash text-mkt-proof grid size-9 place-items-center rounded-sm border">
        <Icon aria-hidden strokeWidth={1.8} className="size-4.5" />
      </span>
      <h3 className="font-mkt-display text-mkt-ink text-heading-sm mt-5 font-semibold">{title}</h3>
      <p className="text-mkt-sm text-mkt-ink-soft mt-2">{blurb}</p>
      <CheckList points={points} />
    </div>
  );
}

export function EnterpriseHero() {
  return (
    <PageHero
      centered
      eyebrow="Enterprise"
      title="AI visibility, with"
      accent="enterprise-grade evidence."
      lead="The platform security teams can verify: deterministic scoring over immutable, provenance-carrying evidence — deployed and operated in our cloud, with the evidence trail your review process needs."
    >
      <div className="mt-9 flex flex-col justify-center gap-2.5 sm:flex-row">
        <ButtonLink href={DEMO_HREF}>
          Book a demo
          <ArrowRight className="size-3.5" aria-hidden />
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
        intro="Every claim below maps to the running platform — bring your security review."
        headingId="enterprise-caps-title"
      />
      <StaggerGroup className="grid gap-4 md:grid-cols-2">
        {OPS_CARDS.map((card) => (
          <StaggerItem key={card.title} className="h-full">
            <CapabilityCard {...card} />
          </StaggerItem>
        ))}
      </StaggerGroup>

      {/* `Reveal` forwards only children/className, so the landmark wrapper
          carries the label — the architecture proof stays queryable. */}
      <div role="region" aria-label="Platform data flow">
        <Reveal className="bg-mkt-surface rounded-mkt-lg shadow-card mt-4 flex flex-wrap items-center gap-x-3 gap-y-2.5 p-6">
          {ARCH_FLOW.map((step) => (
            <Fragment key={step.node}>
              <span className="border-mkt-line bg-mkt-surface text-mkt-ink-soft text-mkt-sm rounded-sm border px-2.5 py-1.5">
                {step.node}
              </span>
              <span aria-hidden className="text-mkt-line-strong">
                {step.arrow}
              </span>
            </Fragment>
          ))}
          <span className="border-mkt-proof-line bg-mkt-wash text-mkt-proof text-mkt-sm rounded-sm border px-2.5 py-1.5">
            AI providers · BYOK
          </span>
        </Reveal>
      </div>
    </Section>
  );
}

export function EnterpriseLimits() {
  return (
    <Section id="limits" tone="sunken" rhythm="loose" aria-label="Custom limits">
      <SectionHeader
        kicker="Custom limits"
        title="Shaped around your requirements."
        intro="Every enterprise agreement starts from these dials — tell us the volumes and we size the plan."
        headingId="enterprise-limits-title"
      />
      <StaggerGroup className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {LIMIT_CELLS.map((cell) => (
          <StaggerItem
            key={cell.label}
            className="rounded-mkt-lg bg-mkt-surface shadow-card h-full p-6"
          >
            <Meta as="p">{cell.label}</Meta>
            <p className="font-mkt-display text-mkt-ink text-mkt-d4 mt-4 font-medium">Custom</p>
            <p className="text-mkt-sm text-mkt-ink-muted mt-2">{cell.desc}</p>
          </StaggerItem>
        ))}
      </StaggerGroup>
      <p className="text-mkt-sm text-mkt-ink-soft mt-8 max-w-[78ch]">
        Searchify does not claim SOC 2 or ISO certifications today.{' '}
        <b className="text-mkt-ink font-semibold">What it offers is verifiable:</b> deterministic
        scoring, immutable evidence, and a provenance stamp on every derived number your team can
        audit line by line.
      </p>
    </Section>
  );
}

/**
 * Enterprise closing band. Its sales action routes through the stable `/demo`
 * funnel so booking/contact configuration remains centralized there.
 */
export function EnterpriseContactCta() {
  return (
    <Section id="contact" tone="surface" rhythm="loose" aria-label="Contact sales">
      <Reveal className="mx-auto max-w-3xl text-center">
        <h2 className="font-mkt-display text-mkt-d2 text-mkt-ink mx-auto mb-5 max-w-[16ch] font-medium">
          Bring AI visibility in-house.
        </h2>
        <p className="text-mkt-lead text-mkt-ink-soft mx-auto max-w-[54ch]">
          Tell us your volumes, constraints and review process — we’ll shape an enterprise plan
          around them, starting with a walkthrough of your own category.
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-2.5 sm:flex-row">
          <ButtonLink href={DEMO_HREF} className="w-full sm:w-auto">
            Book a demo
            <ArrowRight className="size-3.5" aria-hidden />
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
