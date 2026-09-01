import {
  ArrowRight,
  Check,
  FileCheck2,
  KeyRound,
  Scale,
  ShieldCheck,
  UsersRound,
  type LucideIcon,
} from 'lucide-react';

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
    title: 'Keep the credential boundary clear',
    tagline: 'Your provider account remains yours from setup through execution.',
    highlights: [
      'Provider keys are encrypted at rest and resolved only at execution time',
      'Keys are never returned in API responses or logged in clear text',
      'Same-origin API proxying keeps backend topology out of the browser bundle',
    ],
  },
  {
    icon: Scale,
    title: 'Trace every reported number',
    tagline: 'Security, analytics, and growth teams can inspect the same evidence.',
    highlights: [
      'Raw responses are persisted before derived metrics are calculated',
      'Deterministic rules and versioned analysis explain how a result was produced',
      'Coverage, unavailable, and observed-zero states stay distinct',
    ],
  },
  {
    icon: ShieldCheck,
    title: 'Operate with durable runs',
    tagline: 'Long-running crawls and audits have an explicit execution trail.',
    highlights: [
      'PostgreSQL provides durable state and the work queue',
      'Leases, heartbeats, retries, and terminal states are recorded',
      'Runtime Zod and Pydantic contracts validate the browser/API boundary',
    ],
  },
];

const DATA_FLOW_STEPS = [
  { title: 'Browser', detail: 'Authenticated HTTPS' },
  { title: 'Same-origin app', detail: 'Relative API requests' },
  { title: 'API boundary', detail: 'Schema + workspace auth' },
  { title: 'PostgreSQL', detail: 'Evidence + durable queue' },
  { title: 'Workers', detail: 'Leased execution' },
  { title: 'Answer engines', detail: 'Your configured keys' },
] as const;

type EnterpriseFit = {
  icon: LucideIcon;
  title: string;
  description: string;
};

const ENTERPRISE_FIT: readonly EnterpriseFit[] = [
  {
    icon: FileCheck2,
    title: 'Security-led evaluation',
    description:
      'Give reviewers a concise map of credential handling, workspace authorization, evidence retention, and the managed-cloud boundary.',
  },
  {
    icon: UsersRound,
    title: 'Multiple teams or brands',
    description:
      'Keep projects, prompts, provider connections, and audit history scoped to the workspace that owns them.',
  },
  {
    icon: Scale,
    title: 'A measurement program',
    description:
      'Define a prompt portfolio, run comparable audits, and give each reported observation the context needed for review.',
  },
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
      title="AI visibility your security team"
      accent="can inspect."
      lead="Measure how your brand appears in answer engines with a managed, workspace-scoped evidence trail — ready for procurement, security review, and the teams who act on the result."
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
        title="A defensible path from prompt to proof."
        lead="The important boundaries are visible: credentials, evidence, and execution each have one accountable owner."
        headingId="enterprise-caps-title"
      />

      <StaggerGroup className="grid gap-5 md:grid-cols-3">
        {CAPABILITIES.map(({ icon: Icon, title, tagline, highlights }) => (
          <StaggerItem key={title} className="h-full">
            <article className="bg-panel border-border-subtle hover:border-accent-border flex h-full flex-col rounded-2xl border p-7 transition-colors duration-200">
              <div className="bg-accent-soft text-accent-text grid size-10 place-items-center rounded-xl">
                <Icon aria-hidden strokeWidth={1.8} className="size-5" />
              </div>
              <h3 className="website-feature-heading text-foreground mt-5">{title}</h3>
              <p className="website-body text-muted mt-3">{tagline}</p>
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
          <p className="website-body text-muted font-medium">How a request travels</p>
          <span className="text-subtle text-xs">Managed cloud · same-origin boundary</span>
        </div>
        <Reveal className="bg-panel border-border-subtle overflow-hidden rounded-2xl border">
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
                <span className="text-accent-text text-xs font-medium tabular-nums">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <p className="website-body text-foreground font-medium">{step.title}</p>
                <p className="website-label text-muted">{step.detail}</p>
              </li>
            ))}
          </ol>
        </Reveal>
      </section>
    </Section>
  );
}

export function EnterpriseFit() {
  return (
    <Section id="fit" tone="sunken" rhythm="base" aria-label="Who Enterprise is for">
      <SectionHeader
        eyebrow="Designed for review"
        title="A clear fit for high-trust teams."
        lead="Enterprise is the right conversation when your measurement program needs more operating context than a self-serve plan provides."
        headingId="enterprise-fit-title"
      />

      <StaggerGroup className="grid gap-5 md:grid-cols-3">
        {ENTERPRISE_FIT.map(({ icon: Icon, title, description }) => (
          <StaggerItem key={title} className="h-full">
            <article className="bg-panel border-border-subtle flex h-full flex-col rounded-2xl border p-6 md:p-7">
              <Icon aria-hidden className="text-accent-text size-6" strokeWidth={1.8} />
              <h3 className="website-feature-heading text-foreground mt-6">{title}</h3>
              <p className="website-body text-muted mt-3">{description}</p>
            </article>
          </StaggerItem>
        ))}
      </StaggerGroup>
    </Section>
  );
}

export function EnterpriseLimits() {
  return (
    <Section id="limits" tone="paper" rhythm="base" aria-label="Custom limits">
      <SectionHeader
        eyebrow="Sizing"
        title="Scope the agreement around the work."
        lead="Enterprise sizing follows your measurement program: its volume, coverage, teams, history, provider setup, and support model."
        headingId="enterprise-limits-title"
      />

      <Reveal className="bg-panel border-border-subtle overflow-hidden rounded-2xl border">
        <div className="border-border-subtle bg-accent-soft flex flex-col justify-between gap-4 border-b px-6 py-5 md:flex-row md:items-center md:px-8">
          <div>
            <h3 className="website-section-heading text-foreground">Enterprise agreement</h3>
            <p className="website-body text-muted mt-1">Six inputs. One operating plan.</p>
          </div>
          <span className="border-accent-border bg-panel text-accent-text shrink-0 rounded-md border px-4 py-2 text-xs font-medium tracking-wide uppercase">
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
                <h4 className="website-small-heading text-foreground">{item.title}</h4>
                <span className="bg-well text-secondary shrink-0 rounded-md px-2.5 py-1 text-xs font-medium">
                  {item.badge}
                </span>
              </div>
              <p className="website-label text-accent-text mt-3 font-medium">{item.unit}</p>
              <p className="website-body text-muted mt-2">{item.desc}</p>
            </StaggerItem>
          ))}
        </StaggerGroup>
      </Reveal>

      <div className="bg-panel border-border-subtle mt-8 flex flex-col items-start justify-between gap-6 rounded-2xl border p-6 md:flex-row md:items-center md:p-8">
        <div>
          <p className="website-section-heading text-foreground">Audit trail included</p>
          <p className="website-body text-muted mt-2 max-w-[60ch]">
            Your proposal can start with the evidence boundary: deterministic rules, immutable
            artifacts, and provenance on each derived metric.
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
    <Section id="contact" tone="sunken" rhythm="base" aria-label="Contact sales">
      <Reveal className="mx-auto max-w-3xl text-center">
        <h2 className="website-section-heading text-foreground mx-auto mb-4 max-w-[28ch]">
          Give your AI visibility program a reviewable operating model.
        </h2>
        <p className="website-lead text-muted mx-auto max-w-[56ch]">
          Tell us about your volumes, constraints, provider setup, and review process. We will map
          the conversation to the evidence your team needs.
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
