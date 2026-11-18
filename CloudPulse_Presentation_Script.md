# CloudPulse — Presentation Script

> **Speaker notes** for each slide. Estimated total time: **12–15 minutes**.
> Delivery tip: speak slowly on the problem slides, pick up energy on the demo/architecture slides.

---

## Slide 1 — Title Slide
**[~30 seconds]**

Good [morning/afternoon], everyone.

My name is Aakash, and along with my teammates Nazibul and Rishika, we're presenting our Minor Project — **CloudPulse**.

This project sits at the intersection of cloud computing, data engineering, and financial operations. At its core, it answers one question that every engineering team eventually faces: **"Why did our cloud bill just spike?"**

Let's get into it.

---

## Slide 2 — What is CloudPulse?
**[~45 seconds]**

CloudPulse is a **local-first FinOps platform** — FinOps standing for Cloud Financial Operations.

The tagline is simple: **"Know why your cloud bill changed."**

What makes CloudPulse different from the tools you've probably heard of — like AWS Cost Explorer or Datadog — is that it runs entirely **on your machine**. There's no cloud account to connect, no external AI service, no SaaS subscription. You give it your billing exports, and it gives you answers.

It handles spend across **cloud providers** like AWS, GCP, and Azure; **AI APIs** like OpenAI and Anthropic; and **SaaS tools** like Datadog and Snowflake — all in one unified dashboard.

---

## Slide 3 — The Problem
**[~90 seconds]**

To understand why we built this, let's talk about the problem.

Cloud billing today is fundamentally **broken in three ways**.

**First — spend is scattered.** AWS, Google Cloud, Azure, OpenAI, Anthropic, Datadog — they all bill separately, in their own formats, through their own consoles. If you're using five of these, you need to log into five different portals just to get a picture of what you spent last month. There's no unified view.

**Second — AI spend is volatile.** Token-billed LLM APIs like GPT-4o or Claude can jump **ten times** in a single day. A developer changes a prompt, switches a model, or ships a new feature — and suddenly your Anthropic bill triples. You won't even know until the invoice arrives.

**Third — alerts without reasons.** Most monitoring tools will tell you *that* your spend went up. But they won't tell you *which* service, which resource, or which AI model caused it. And critically — they won't tell you whether it was **usage** that grew or **price** that changed. Those are very different problems with very different fixes.

The result? The bill arrives — weeks late — as one big number, with no owner and no cause. That's what CloudPulse is designed to fix.

---

## Slide 4 — The Solution
**[~75 seconds]**

CloudPulse addresses this with a four-step loop.

**Import.** You upload your billing CSV exports — from any of 18+ supported providers — and CloudPulse validates every single row. If a row is malformed, it tells you the exact line and column. Nothing gets imported silently.

**Analyse.** Once the data is in, you get breakdowns by provider, service, AI model, project, and environment. You can drill down to exactly who spent what, with a **month-end forecast** so you're not surprised when the bill arrives.

**Detect and Explain.** This is the core of CloudPulse. It uses statistical methods — specifically robust median baselines and z-scores — to flag unusual spend. And crucially, every anomaly comes with **stored evidence**: the actual value, the expected baseline, and the statistical threshold that was crossed. No black box.

**Act.** Flagged anomalies become **incidents** with an acknowledgement and resolution workflow. Budgets fire **email or Slack alerts** when thresholds are hit. The whole team stays on track.

And again — this all runs **locally**. No cloud credentials required.

---

## Slide 5 — FinOps: Everyone Owns the Cloud Bill
**[~60 seconds]**

Let's take a step back and explain the discipline CloudPulse is built around — **FinOps**.

FinOps, or Cloud Financial Operations, is the practice of making **engineering, finance, and product teams jointly accountable** for cloud spend. Historically, engineers build and ship, finance pays the bill, and product weighs the value — but none of them talk to each other about cost.

FinOps breaks that into a **continuous loop of three phases**:

1. **Inform** — *Where is the money going?* Give every team visibility into what's being spent and who owns it.
2. **Optimize** — *What changed, and why?* Find the spikes, find the waste, find the cause.
3. **Operate** — *How do we stay on track?* Budgets, alerts, governance, and accountability.

CloudPulse is designed to deliver all three of these phases for a small engineering team — without needing a dedicated FinOps engineer or a \$5,000-a-month SaaS contract.

---

## Slide 6 — How CloudPulse Delivers the FinOps Loop
**[~75 seconds]**

Here's exactly how CloudPulse maps to those three phases.

For **Inform**: CloudPulse maintains one unified cost model across 18+ providers. It categorizes spend into cloud, AI, and SaaS, and provides breakdowns by provider, service, AI model, project, and environment. Allocation rules let you assign untagged costs to the right team or project.

For **Optimize**: The anomaly detection engine stores evidence for every flagged spend event — not just a flag, but the actual values and thresholds. The investigation view shows the largest cost contributors, identifies new resources and regions that appeared, and — critically — separates **usage-driven** increases from **price-driven** ones. A usage spike and a price change are very different problems.

For **Operate**: Monthly, quarterly, or yearly budgets with live forecasts. Alerts go out by email or Slack-compatible webhook — and they're smart enough to fire **once per threshold per period**, not on every check. The incident workflow tracks each anomaly from detection to resolution, with notes and a full audit timeline.

---

## Slide 7 — Data Pipeline: From Export to Insight
**[~75 seconds]**

Let's look at how data flows through the system.

It starts with a **billing CSV export** — from AWS, GCP, Azure, OpenAI, Anthropic, Datadog, or any CSV-exporting provider.

That file goes through **four pipeline stages** before anything is stored:

1. **Validate** — every row is checked for required fields, correct types, and sensible values. Errors are reported by line and column, and if anything fails, nothing is imported.
2. **Normalize** — provider names are standardized, categories are assigned, AI models are extracted, and token counts are parsed.
3. **Deduplicate** — every record gets a **SHA-256 fingerprint**. If you re-upload a file or upload overlapping date ranges, duplicate records are silently skipped. You can never double-count a cost.
4. **Store** — everything lands in one canonical `billing_records` table.

From there, **analytics, anomaly detection, investigations, and budgets all read the same table**. That's not an accident — it means the number on your Overview dashboard and the number inside an incident will always agree. There's no inconsistency between views.

Money is stored as exact **decimals**, never floating point. We never lose precision on a currency amount.

---

## Slide 8 — Architecture
**[~60 seconds]**

Here's the full architecture — and yes, everything in this diagram runs on your laptop.

The **Dashboard** is a Next.js 16 app running in your browser. It talks to a **FastAPI backend** over a bearer token, with role-based access control at every route.

The API hands off to an **import pipeline** for CSV processing, and enqueues background work into **Redis**. A **Celery worker** picks those jobs up — running anomaly detection every 6 hours, budget checks every hour, and alert retries every 10 minutes.

**PostgreSQL 16** is the single source of truth — 15 tables, with money stored as exact decimals, never floats. **Mailpit** acts as a local SMTP inbox so you can test email alerts without a real mail server.

Every port is bound to `127.0.0.1`. Nothing is exposed to the network by default.

---

## Slide 9 — Case Study: Claude API +378%
**[~90 seconds]**

Let me show you what CloudPulse looks like in practice.

This is based on our **synthetic sample dataset** — 90 days of realistic cloud, AI, and SaaS spend with three injected anomalies.

One of those anomalies is a **Claude API spike on October 5th**. The daily cost went from an expected **\$7.35** to an actual **\$35.14** — a **+378% increase**.

Here's what CloudPulse's investigation view tells you:

**Is it usage or price?** Usage. Output tokens grew **11.4 times** that day, and cost grew proportionally. The price per token did not change.

**Which model?** `claude-sonnet-4-5`.

**Which project?** `support-assistant`.

**How severe?** Low — because while the percentage is dramatic, the absolute dollar amount is small.

This is the core value proposition. Without CloudPulse, you'd see a line item on the Anthropic invoice. With CloudPulse, you know *exactly* which model, which project, and *why* the cost grew — and you have the statistical evidence to back it up.

The incident workflow then lets you **acknowledge** it, add context notes, and **resolve** it — with a full timeline that's preserved in the audit log.

---

## Slide 10 — Built Like a Production System
**[~60 seconds]**

We want to be clear: this isn't a prototype or a demo app. CloudPulse is built to production standards.

The stack is modern and chosen deliberately: **Next.js 16** with React 19, TypeScript in strict mode, and Tailwind CSS 4 on the front end. **FastAPI** with Pydantic 2 and SQLAlchemy 2 on the back end. **PostgreSQL 16** with money stored as `NUMERIC(18,8)` — never floats.

For quality:
- **205 backend tests** run against a real PostgreSQL database — covering parsing, detection, analytics, auth, and an access-policy test on every single API route.
- **15 end-to-end browser tests** with Playwright — covering the full user journey from sign-in to incident resolution.
- **GitHub Actions CI** runs the full suite on every push — secret scan, backend tests, frontend build, e2e, and Docker builds.

Security: scrypt-hashed passwords, opaque revocable session tokens, account lockout after five failed logins, and a full audit log.

---

## Slide 12 — Roadmap
**[~45 seconds]**

Here's where CloudPulse stands and where it's going.

**What's built:** The complete core platform — ingestion, analytics, anomaly detection, incidents, budgets, alerts, auth, RBAC, audit log, CI pipeline, and four live connectors: AWS CUR from S3, AWS Cost Explorer, OpenAI usage API, and Anthropic usage API.

**What's next:** Unit economics. The ability to calculate cost *per customer*, per feature, or per 1,000 API requests — from tagged spend that's already in the system.

**Later on the horizon:** Multi-tenant workspaces for separate organizations, SSO, and HTTPS-ready sessions for network deployment. And savings insights — covering reserved capacity and savings plan opportunities from the billing data you already have.

---

## Slide 13 — Thank You
**[~30 seconds]**

That's CloudPulse.

A local-first FinOps platform that turns billing exports into answers — across cloud, AI, and SaaS spend — with explainable anomaly detection, incident workflows, budgets, and alerts. No cloud account, no external AI, no SaaS subscription.

If you'd like to try it, it's one command:

```
docker compose --profile app up -d --build
```

We're happy to take any questions. Thank you.

---

*Total estimated time: 12–15 minutes. Adjust pace on slides 3, 7, and 9 for maximum impact.*
