import Link from "next/link";
import type { ReactNode } from "react";

import { ArrowDownIcon, LayoutDashboardIcon } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { ProviderMarquee } from "@/components/brand/provider-marquee";
import { HeroSection } from "@/components/ui/hero-section";
import { buttonClass, cx } from "@/components/ui/primitives";

const NAV = [
  { href: "#platform", label: "Platform" },
  { href: "#how-it-works", label: "How it works" },
  { href: "#features", label: "Features" },
  { href: "#faq", label: "FAQ" },
];

export default function LandingPage() {
  return (
    <div className="bg-white text-slate-900">
      <SiteHeader />
      <main>
        <Hero />
        <ProviderMarquee />
        <Pillars />
        <Workflow />
        <Features />
        <Principles />
        <Faq />
        <ClosingCta />
      </main>
      <SiteFooter />
    </div>
  );
}

function Container({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("mx-auto w-full max-w-6xl px-4 sm:px-6", className)}>{children}</div>;
}

function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-white/10 bg-ink/95 backdrop-blur">
      <Container className="flex h-16 items-center gap-6">
        <Link href="/" aria-label="CloudPulse home">
          <Logo inverted />
        </Link>
        <nav aria-label="Primary" className="hidden flex-1 md:block">
          <ul className="flex gap-6 text-sm text-slate-300">
            {NAV.map((item) => (
              <li key={item.href}>
                <a href={item.href} className="hover:text-white">
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/dashboard/imports" className="hidden px-3 text-sm font-medium text-slate-200 hover:text-white sm:inline">
            Import data
          </Link>
          <Link href="/dashboard" className={buttonClass("primary")}>
            Open dashboard
          </Link>
        </div>
      </Container>
    </header>
  );
}

function Hero() {
  return (
    // `.dark` scopes the shadcn tokens to the navy "ink" palette, continuing the header.
    <div className="dark">
      <HeroSection
        title="Know why your cloud bill changed"
        description="CloudPulse turns cloud, AI and SaaS billing exports into cost analytics, flags unusual spend with explainable statistics, and shows the evidence behind every increase."
        actions={[
          {
            text: "Open the dashboard",
            href: "/dashboard",
            variant: "default",
            icon: <LayoutDashboardIcon className="h-5 w-5" aria-hidden />,
          },
          {
            text: "See how it works",
            href: "#how-it-works",
            variant: "glow",
            icon: <ArrowDownIcon className="h-5 w-5" aria-hidden />,
          },
        ]}
        image={{
          // CloudPulse is light-only for now (docs/design.md), so both themes use the same screenshot.
          light: "/images/cloudpulse-dashboard.png",
          dark: "/images/cloudpulse-dashboard.png",
          alt: "CloudPulse overview dashboard with the built-in sample data: month-to-date spend, month-end forecast, a daily spend spike and the top services.",
        }}
      />
    </div>
  );
}

const PILLARS = [
  {
    title: "Allocate",
    body: "Normalize cloud, AI model API and SaaS billing exports into one canonical model and break spend down by provider, service, model, resource, region, project and environment. Allocation rules attribute untagged costs.",
    icon: "M4 6h16M4 12h10M4 18h6",
  },
  {
    title: "Detect",
    body: "Day-of-week-aware median baselines, robust z-scores and configurable thresholds flag real increases, and refuse to judge series without enough history.",
    icon: "M3 12h4l3 7 4-14 3 7h4",
  },
  {
    title: "Investigate",
    body: "Every incident comes with measured evidence: largest contributors, new resources and regions, usage-versus-price analysis, and suggestions tied to that evidence.",
    icon: "M11 4a7 7 0 105.2 11.7L21 20.5",
  },
];

function SectionHeading({ eyebrow, title, body }: { eyebrow: string; title: string; body?: string }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <p className="text-sm font-semibold uppercase tracking-wider text-brand-600">{eyebrow}</p>
      <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h2>
      {body && <p className="mt-4 text-lg text-slate-600">{body}</p>}
    </div>
  );
}

function Pillars() {
  return (
    <section id="platform" className="scroll-mt-16 py-20 sm:py-24">
      <Container>
        <SectionHeading
          eyebrow="Platform"
          title="From cost visibility to cost accountability"
          body="CloudPulse focuses on one thing: helping small engineering teams understand where cloud and AI money goes and why it changed."
        />
        <div className="mt-14 grid gap-6 md:grid-cols-3">
          {PILLARS.map((pillar) => (
            <div key={pillar.title} className="rounded-2xl border border-slate-200 p-6 transition-shadow hover:shadow-lg hover:shadow-slate-200/60">
              <div className="flex size-11 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
                <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d={pillar.icon} />
                </svg>
              </div>
              <h3 className="mt-5 text-lg font-semibold">{pillar.title}</h3>
              <p className="mt-2 leading-relaxed text-slate-600">{pillar.body}</p>
            </div>
          ))}
        </div>
      </Container>
    </section>
  );
}

const STEPS = [
  {
    title: "Import billing data",
    body: "Upload a CSV from any provider (AWS, Google Cloud, Azure, OpenAI, Anthropic and more) in the CloudPulse format, or an AWS Cost and Usage Report. Every row is validated with line-level errors, and re-imported records are de-duplicated.",
  },
  {
    title: "Detect unusual spend",
    body: "After each import and on a schedule, every service's daily cost is compared with its expected baseline. Consecutive anomalous days become a single incident.",
  },
  {
    title: "Investigate with evidence",
    body: "See actual versus expected, the contributors behind the change and what to check next. Acknowledge, take notes and resolve with a full timeline.",
  },
];

function Workflow() {
  return (
    <section id="how-it-works" className="scroll-mt-16 bg-slate-50 py-20 sm:py-24">
      <Container>
        <SectionHeading eyebrow="How it works" title="From raw spend to real answers" />
        <ol className="mt-14 grid gap-6 md:grid-cols-3">
          {STEPS.map((step, i) => (
            <li key={step.title} className="relative rounded-2xl bg-white p-6 ring-1 ring-slate-200">
              <span className="flex size-9 items-center justify-center rounded-full bg-ink text-sm font-semibold text-white">
                {i + 1}
              </span>
              <h3 className="mt-4 text-lg font-semibold">{step.title}</h3>
              <p className="mt-2 leading-relaxed text-slate-600">{step.body}</p>
            </li>
          ))}
        </ol>
      </Container>
    </section>
  );
}

const FEATURES: { title: string; body: string; points: string[]; visual: ReactNode }[] = [
  {
    title: "Evidence-based investigation",
    body: "When spend jumps, CloudPulse compares the incident period with the preceding baseline across services, resources, regions, usage types and projects.",
    points: [
      "Largest contributors ranked by their share of the increase",
      "New resources and regions with no baseline spend called out",
      "Usage-driven versus price-driven changes separated when quantities exist",
      "“The cause cannot be determined” when the data cannot support a conclusion",
    ],
    visual: (
      <ul className="space-y-3">
        {[
          ["Resource", "i-0f3e9a7c5b1d2468a"],
          ["Region", "us-west-2"],
          ["Usage type", "BoxUsage:p4d.24xlarge"],
        ].map(([dimension, label]) => (
          <li key={label}>
            <div className="flex flex-wrap justify-between gap-x-3 text-sm">
              <span>
                <span className="text-slate-500">{dimension} · </span>
                <span className="font-mono text-[0.8rem]">{label}</span>
              </span>
              <span className="font-medium">+$1,376.45 · 100% · new</span>
            </div>
            <div className="mt-1.5 h-2 rounded-full bg-slate-100">
              <div className="h-full w-full rounded-full bg-brand-600" />
            </div>
          </li>
        ))}
      </ul>
    ),
  },
  {
    title: "AI and LLM spend, next to your cloud bill",
    body: "Token-billed model APIs are imported like any other cost line, with the model they were spent on. See which models, teams and token types drive AI spend, and catch runaway usage the day it happens.",
    points: [
      "Spend by category: cloud infrastructure, AI model APIs and SaaS",
      "Group and filter by model, such as gpt-4o or claude-sonnet-4-5",
      "Token spikes investigated like any incident: usage-driven or price-driven",
      "Suggestions to check prompt sizes, output limits, retries and caching",
    ],
    visual: (
      <div>
        <p className="text-sm font-medium">AI model spend · last 30 days</p>
        <ul className="mt-3 space-y-3">
          {[
            ["claude-sonnet-4-5", "$215.60", "45.0%", "w-[45%]"],
            ["gpt-4o", "$185.19", "38.6%", "w-[38.6%]"],
            ["gemini-2.5-flash", "$57.04", "11.9%", "w-[11.9%]"],
            ["text-embedding-3-small", "$21.53", "4.5%", "w-[4.5%]"],
          ].map(([model, cost, share, width]) => (
            <li key={model}>
              <div className="flex flex-wrap justify-between gap-x-3 text-sm">
                <span className="font-mono text-[0.8rem]">{model}</span>
                <span className="font-medium">
                  {cost} <span className="font-normal text-slate-500">· {share}</span>
                </span>
              </div>
              <div className="mt-1.5 h-2 rounded-full bg-slate-100">
                <div className={cx("h-full rounded-full bg-brand-600", width)} />
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
          <span className="font-medium">Oct 5 · Claude API:</span> output tokens rose 11.4× while cost rose 11.4×, so the
          increase is usage-driven.
        </p>
      </div>
    ),
  },
  {
    title: "Explainable anomaly detection",
    body: "No black box. Each detection stores the observed cost, expected baseline, thresholds, robust z-score and the baseline values it used.",
    points: [
      "Configurable percentage, amount and z-score thresholds",
      "Same-weekday medians handle weekday and weekend patterns",
      "Minimum-history rule: no anomaly is claimed without a trustworthy baseline",
      "Severity requires both a relative and an absolute impact",
    ],
    visual: (
      <dl className="grid grid-cols-2 gap-3 text-sm">
        {[
          ["Observed (Oct 7)", "$849.13"],
          ["Expected", "$62.59"],
          ["Deviation", "+$786.54 · +1,256.6%"],
          ["Baseline", "Same-weekday median"],
        ].map(([k, v]) => (
          <div key={k} className="rounded-lg bg-slate-50 p-3">
            <dt className="text-xs text-slate-500">{k}</dt>
            <dd className="mt-0.5 font-semibold">{v}</dd>
          </div>
        ))}
      </dl>
    ),
  },
  {
    title: "Budgets, forecasts and alerts",
    body: "Track monthly, quarterly or yearly budgets for all spend or a single service, project or environment, with a month-end projection based on documented assumptions.",
    points: [
      "Threshold alerts by e-mail or webhook, once per threshold per period",
      "Optional repeat policy while a budget stays exceeded",
      "Every delivery attempt recorded, with failures retried",
      "Notification failures never block imports or detection",
    ],
    visual: (
      <div>
        <div className="flex justify-between text-sm">
          <span className="font-medium">Monthly cloud and AI budget · $3,000</span>
          <span className="text-red-700">Over budget</span>
        </div>
        <div className="mt-1.5 h-2 rounded-full bg-red-100">
          <div className="h-full w-full rounded-full bg-critical" />
        </div>
        <p className="mt-2 text-sm text-slate-600">$3,346.79 spent by Oct 11 · 111.6% · thresholds 50%, 80%, 100% crossed</p>
        <p className="mt-3 rounded-lg bg-slate-50 p-3 font-mono text-[0.75rem] text-slate-700">
          [CloudPulse] Budget &apos;Monthly cloud and AI budget&apos; reached 111.56% (threshold 100%)
        </p>
      </div>
    ),
  },
];

function Features() {
  return (
    <section id="features" className="scroll-mt-16 py-20 sm:py-24">
      <Container>
        <SectionHeading eyebrow="Features" title="Built for the moment your bill surprises you" />
        <div className="mt-16 space-y-16">
          {FEATURES.map((feature, i) => (
            <div key={feature.title} className="grid items-center gap-10 lg:grid-cols-2">
              <div className={cx(i % 2 === 1 && "lg:order-2")}>
                <h3 className="text-2xl font-semibold tracking-tight">{feature.title}</h3>
                <p className="mt-3 text-lg leading-relaxed text-slate-600">{feature.body}</p>
                <ul className="mt-6 space-y-3">
                  {feature.points.map((point) => (
                    <li key={point} className="flex gap-3 text-slate-700">
                      <svg viewBox="0 0 20 20" className="mt-0.5 size-5 shrink-0 text-brand-600" fill="currentColor" aria-hidden>
                        <path fillRule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-8 8a1 1 0 01-1.4 0l-4-4a1 1 0 011.4-1.4L8 12.6l7.3-7.3a1 1 0 011.4 0z" clipRule="evenodd" />
                      </svg>
                      {point}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-gradient-to-b from-slate-50 to-white p-6 shadow-sm">
                <div className="rounded-xl bg-white p-5 ring-1 ring-slate-200">{feature.visual}</div>
                <p className="mt-3 text-center text-xs text-slate-500">
                  Values from the built-in sample dataset{i === FEATURES.length - 1 ? " with an example $3,000 monthly budget" : ""}
                </p>
              </div>
            </div>
          ))}
        </div>
      </Container>
    </section>
  );
}

const PRINCIPLES = [
  ["Exact money", "Amounts are stored as decimals, never floating point, and returned as decimal strings."],
  ["One currency at a time", "Different currencies are never added together without a conversion rate."],
  ["Missing is not zero", "Days without billing data are shown as gaps and excluded from averages."],
  ["No invented causes", "Explanations come from measured values. When the data is insufficient, CloudPulse says so."],
];

function Principles() {
  return (
    <section className="bg-ink py-20 text-white sm:py-24">
      <Container>
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold uppercase tracking-wider text-brand-200">Principles</p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Numbers you can defend</h2>
        </div>
        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {PRINCIPLES.map(([title, body]) => (
            <div key={title} className="rounded-2xl border border-white/10 bg-white/5 p-6">
              <h3 className="font-semibold">{title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-300">{body}</p>
            </div>
          ))}
        </div>
      </Container>
    </section>
  );
}

const FAQS = [
  [
    "Do I need an AWS account or cloud credentials?",
    "No. CloudPulse runs locally with Docker Compose and works from CSV billing exports. A synthetic dataset is built in, so you can explore every feature without any cloud account.",
  ],
  [
    "Which providers can I import?",
    "Any provider that can export costs as CSV: AWS, Google Cloud, Microsoft Azure, Oracle Cloud, OpenAI, Anthropic, Google Gemini, Mistral, Datadog, Snowflake and more. Known provider names such as \"Microsoft Azure\" are normalized automatically and grouped into cloud, AI and SaaS categories; any other provider is kept as-is.",
  ],
  [
    "Can CloudPulse track LLM and AI API costs?",
    "Yes. Add a model column (for example gpt-4o or claude-sonnet-4-5) and token counts as the usage quantity. Spend can then be grouped by model, budgets and anomaly detection can be scoped to a model or to AI spend as a whole, and investigations separate usage-driven token growth from price changes. CloudPulse reads exported files; it does not call provider APIs.",
  ],
  [
    "Which billing formats are supported?",
    "The CloudPulse canonical CSV format, plus AWS Cost and Usage Report column names (for example lineItem/UnblendedCost). Header names are matched case-insensitively, and a downloadable template documents every field.",
  ],
  [
    "How does anomaly detection work?",
    "For each day, CloudPulse compares cost with an expected baseline: the median of the same weekday over recent weeks, or a rolling median. A day is anomalous only when the percentage, amount and robust z-score thresholds are all met, and only after a minimum amount of history exists.",
  ],
  [
    "Does CloudPulse use AI to explain incidents?",
    "No. CloudPulse tracks what you spend on AI, but its explanations are deterministic and computed from your billing records, so the same data always produces the same explanation. Nothing is sent to an external service.",
  ],
  [
    "What happens if I import the same file twice?",
    "An identical file is rejected. Overlapping exports are handled record by record: rows already stored are skipped and reported as duplicates, so costs are never double-counted.",
  ],
  [
    "Where do alerts go?",
    "To the e-mail and webhook channels you configure. Locally, e-mail is captured by Mailpit so you can see test alerts without a mail server. Webhook payloads include a Slack-compatible text field.",
  ],
];

function Faq() {
  return (
    <section id="faq" className="scroll-mt-16 py-20 sm:py-24">
      <Container className="max-w-3xl">
        <SectionHeading eyebrow="FAQ" title="Questions, answered" />
        <div className="mt-12 divide-y divide-slate-200 rounded-2xl border border-slate-200">
          {FAQS.map(([question, answer]) => (
            <details key={question} className="group p-5 [&_summary::-webkit-details-marker]:hidden">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
                {question}
                <span aria-hidden className="text-slate-400 transition-transform group-open:rotate-45">
                  +
                </span>
              </summary>
              <p className="mt-3 leading-relaxed text-slate-600">{answer}</p>
            </details>
          ))}
        </div>
      </Container>
    </section>
  );
}

function ClosingCta() {
  return (
    <section className="pb-20 sm:pb-24">
      <Container>
        <div className="rounded-3xl bg-gradient-to-br from-brand-700 to-ink px-6 py-14 text-center text-white sm:px-12">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">See CloudPulse on real-looking data</h2>
          <p className="mx-auto mt-4 max-w-xl text-lg text-blue-100">
            Load the sample dataset of cloud, AI and SaaS spend in one click, find the three injected anomalies and follow the evidence.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Link href="/dashboard" className="inline-flex h-11 items-center rounded-lg bg-white px-5 font-medium text-ink hover:bg-blue-50">
              Open the dashboard
            </Link>
            <Link href="/dashboard/imports" className="inline-flex h-11 items-center rounded-lg border border-white/30 px-5 font-medium hover:bg-white/10">
              Import billing data
            </Link>
          </div>
        </div>
      </Container>
    </section>
  );
}

function SiteFooter() {
  return (
    <footer className="border-t border-slate-200 py-10">
      <Container className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <Logo />
          <p className="mt-2 text-sm text-slate-500">Open, local-first cost intelligence for cloud and AI spend. A student engineering project.</p>
        </div>
        <nav aria-label="Footer">
          <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-slate-600">
            <li><Link href="/dashboard" className="hover:text-slate-900">Dashboard</Link></li>
            <li><Link href="/dashboard/costs" className="hover:text-slate-900">Cost explorer</Link></li>
            <li><Link href="/dashboard/incidents" className="hover:text-slate-900">Incidents</Link></li>
            <li><Link href="/dashboard/imports" className="hover:text-slate-900">Imports</Link></li>
            <li><a href="#faq" className="hover:text-slate-900">FAQ</a></li>
          </ul>
        </nav>
      </Container>
    </footer>
  );
}
