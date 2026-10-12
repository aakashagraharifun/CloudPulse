import Link from "next/link";
import type { ReactNode } from "react";

import { Logo } from "@/components/brand/logo";
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
    <section className="relative overflow-hidden bg-ink text-white">
      <div
        aria-hidden
        className="absolute inset-0 opacity-40"
        style={{
          backgroundImage:
            "radial-gradient(60rem 30rem at 85% -10%, rgba(42,120,214,0.45), transparent 60%), radial-gradient(40rem 20rem at -10% 110%, rgba(27,175,122,0.18), transparent 60%)",
        }}
      />
      <Container className="relative grid items-center gap-12 py-20 lg:grid-cols-2 lg:py-28">
        <div>
          <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-medium text-slate-200">
            <span className="size-1.5 rounded-full bg-green-400" aria-hidden />
            Developer-first cloud cost intelligence
          </p>
          <h1 className="text-4xl font-semibold leading-tight tracking-tight sm:text-5xl lg:text-[3.5rem]">
            Know <span className="text-brand-200">why</span> your cloud bill changed.
          </h1>
          <p className="mt-5 max-w-xl text-lg leading-relaxed text-slate-300">
            CloudPulse turns raw billing exports into cost analytics, flags unusual spend with explainable statistics, and
            shows the evidence behind every increase: which service, resource and region, by how much, and compared with
            what.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/dashboard" className={cx(buttonClass("primary"), "h-11 px-5 text-base")}>
              Open the dashboard
            </Link>
            <a
              href="#how-it-works"
              className="inline-flex h-11 items-center rounded-lg border border-white/20 px-5 text-base font-medium text-white hover:bg-white/10"
            >
              See how it works
            </a>
          </div>
          <p className="mt-6 text-sm text-slate-400">
            Runs entirely on your machine. No cloud credentials, paid APIs or AI services required.
          </p>
        </div>
        <HeroPreview />
      </Container>
    </section>
  );
}

/** A static rendering of the investigation view, using the built-in sample dataset's numbers. */
function HeroPreview() {
  // EC2 daily cost in the sample data, Sep 28 - Oct 11 (normal ~$62.59/day; spikes $849.13 and $652.50).
  const bars = [...Array(9).fill(7.4), 100, 76.8, 7.4, 7.4, 7.4];
  return (
    <figure className="relative">
      <div className="rounded-2xl border border-white/10 bg-white p-5 text-slate-900 shadow-2xl shadow-black/40">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-medium text-slate-500">Incident · Service</p>
            <p className="text-base font-semibold">Amazon Elastic Compute Cloud</p>
          </div>
          <span className="rounded-md bg-orange-50 px-2 py-0.5 text-xs font-medium text-orange-800 ring-1 ring-inset ring-orange-200">
            ● High
          </span>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
          <div className="rounded-lg bg-slate-50 p-3">
            <p className="text-xs text-slate-500">Actual</p>
            <p className="font-semibold">$1,501.63</p>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <p className="text-xs text-slate-500">Expected</p>
            <p className="font-semibold">$125.18</p>
          </div>
          <div className="rounded-lg bg-red-50 p-3">
            <p className="text-xs text-red-700">Above expected</p>
            <p className="font-semibold text-red-700">+$1,376.45</p>
          </div>
        </div>
        <div className="mt-4 flex h-24 items-end gap-1.5" aria-hidden>
          {bars.map((h, i) => (
            <div
              key={i}
              className={cx("flex-1 rounded-t", i === 9 || i === 10 ? "bg-critical" : "bg-brand-600/80")}
              style={{ height: `${h}%` }}
            />
          ))}
        </div>
        <div className="mt-4 rounded-lg border border-slate-200 p-3 text-sm">
          <p className="font-medium">Largest contributor</p>
          <p className="mt-1 text-slate-600">
            Resource <span className="font-mono text-[0.8rem] text-slate-900">i-0f3e9a7c5b1d2468a</span> in us-west-2 had no
            baseline spend and accounts for 100% of the increase.
          </p>
        </div>
      </div>
      <figcaption className="mt-3 text-center text-xs text-slate-400">
        Illustration using CloudPulse’s built-in synthetic sample dataset.
      </figcaption>
    </figure>
  );
}

const PILLARS = [
  {
    title: "Allocate",
    body: "Normalize billing exports into one canonical model and break spend down by provider, service, resource, region, project and environment. Allocation rules attribute untagged costs.",
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
          body="CloudPulse focuses on one thing: helping small engineering teams understand where cloud money goes and why it changed."
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
    body: "Upload a CSV in the CloudPulse format or an AWS Cost and Usage Report export. Every row is validated with line-level errors, and re-imported records are de-duplicated.",
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
          <span className="font-medium">Monthly cloud budget · $3,000</span>
          <span className="text-red-700">Over budget</span>
        </div>
        <div className="mt-1.5 h-2 rounded-full bg-red-100">
          <div className="h-full w-full rounded-full bg-critical" />
        </div>
        <p className="mt-2 text-sm text-slate-600">$3,008.37 spent by Oct 11 · 100.3% · thresholds 50%, 80%, 100% crossed</p>
        <p className="mt-3 rounded-lg bg-slate-50 p-3 font-mono text-[0.75rem] text-slate-700">
          [CloudPulse] Budget &apos;Monthly cloud budget&apos; reached 100.28% (threshold 100%)
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
                  Values from the built-in sample dataset{i === 2 ? " with an example $3,000 monthly budget" : ""}
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
    "Which billing formats are supported?",
    "The CloudPulse canonical CSV format, plus AWS Cost and Usage Report column names (for example lineItem/UnblendedCost). Header names are matched case-insensitively, and a downloadable template documents every field.",
  ],
  [
    "How does anomaly detection work?",
    "For each day, CloudPulse compares cost with an expected baseline: the median of the same weekday over recent weeks, or a rolling median. A day is anomalous only when the percentage, amount and robust z-score thresholds are all met, and only after a minimum amount of history exists.",
  ],
  [
    "Does CloudPulse use AI to explain incidents?",
    "No. Explanations are deterministic and computed from your billing records, so the same data always produces the same explanation. Nothing is sent to an external service.",
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
            Load the sample dataset in one click, find the two injected anomalies and follow the evidence.
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
          <p className="mt-2 text-sm text-slate-500">Open, local-first cloud cost intelligence. A student engineering project.</p>
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
