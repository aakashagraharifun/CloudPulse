# CloudPulse

**Developer-first cloud cost intelligence and anomaly detection.**

CloudPulse turns cloud billing exports into cost analytics, detects unusual spending with explainable statistics, and shows the evidence behind every increase. You see actual versus expected cost, the largest contributors, new resources and regions, whether usage or price drove the change, and what to check next. When the billing data cannot support a conclusion, CloudPulse says so instead of guessing.

It runs entirely on your machine. You do not need a cloud account, paid API or AI service. A deterministic synthetic dataset with two injected anomalies is built in.

| | |
| --- | --- |
| Frontend | Next.js 16 (App Router, TypeScript strict), Tailwind CSS 4, Recharts 3 |
| Backend | Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, pandas |
| Infrastructure | PostgreSQL 16, Redis 7, Celery 5, Mailpit (local e-mail), Docker Compose |
| Quality | pytest (114 tests, real PostgreSQL), ruff, ESLint, TypeScript |

## Features (milestones 1–7)

- **Billing ingestion:** CSV upload with size, encoding, header and per-row validation. Errors are reported by line and column, and nothing is imported if any row is invalid. AWS CUR column names are recognised. Identical files and duplicate records are rejected or skipped. Every import's status is tracked.
- **Cost analytics:** totals, daily, weekly and monthly series, and breakdowns by provider, account, service, region, resource, usage type, project and environment. Each view compares with the previous period. Missing days are shown as gaps, never as zero. Currencies are never mixed. A month-end forecast is included.
- **Cost allocation rules:** attribute untagged costs to projects and environments.
- **Anomaly detection:** same-weekday or rolling **median** baselines, robust z-score, percentage, absolute and new-spend thresholds, and a minimum-history rule. Every decision is persisted with its evidence.
- **Investigation:** contributors by dimension, new-resource and new-region detection, usage-versus-price analysis, deterministic explanations with a confidence statement, evidence-tied suggestions, and an incident workflow (acknowledge, notes, resolve, reopen) with a timeline. Repeated runs never create duplicate incidents.
- **Budgets and notifications:** monthly, quarterly and yearly budgets for all spend or a single scope, with utilization and projection. Threshold alerts go out by e-mail or webhook, once per threshold per period (with an optional repeat policy). Every delivery attempt is logged, and failed deliveries are retried.
- **Dashboard:** landing page, overview, cost explorer, incidents, investigation, budgets, imports and settings. Every page has loading, empty, error and success states, and the layout is responsive down to 360px.

## Quick start (Windows, PowerShell, Docker Desktop)

Prerequisites: [Docker Desktop](https://www.docker.com/products/docker-desktop/) running, and Git.

```powershell
git clone <your-repo-url> CloudPulse
cd CloudPulse
Copy-Item .env.example .env          # then edit POSTGRES_PASSWORD in .env
docker compose --profile app up -d --build
```

| Open | URL |
| --- | --- |
| Dashboard | http://localhost:3000 |
| API docs (OpenAPI / Swagger) | http://127.0.0.1:8000/docs |
| Local e-mail inbox (Mailpit) | http://127.0.0.1:8025 |

Then follow the demo:

1. **Imports → Load sample data.** This loads 90 days of synthetic billing ending yesterday. Detection runs automatically.
2. **Overview** and **Cost explorer:** see spend, top services and the forecast. Click a service to drill down.
3. **Incidents:** open the *Amazon Elastic Compute Cloud* spike and follow the evidence to the new GPU instance in `us-west-2`.
4. **Settings → Notifications → Add channel** (e-mail `you@example.com`), then **Send test**. The message appears in Mailpit.
5. **Budgets → New budget** ($3,000 monthly), then **Check budgets now**. The threshold alert arrives in Mailpit.

Stop everything with `docker compose --profile app down`. Your data is kept in Docker volumes.

To develop with hot reload instead, run only the infrastructure in Docker and the API and frontend on your machine. See **[docs/development.md](docs/development.md)**.

## Documentation

| Document | Contents |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Components, data flow, design decisions |
| [docs/database-schema.md](docs/database-schema.md) | Tables, relationships, constraints |
| [docs/api.md](docs/api.md) | Endpoints with example requests |
| [docs/anomaly-detection.md](docs/anomaly-detection.md) | Detection and investigation logic, limitations |
| [docs/design.md](docs/design.md) | Design system: color, type, components, charts |
| [docs/development.md](docs/development.md) | Local setup, tests, troubleshooting (Windows) |
| [sample-data/README.md](sample-data/README.md) | The synthetic dataset and injected anomalies |

## Project structure

```
CloudPulse/
├── backend/                FastAPI app, Celery worker, Alembic migrations, tests
│   ├── app/
│   │   ├── api/v1/         REST routes (versioned under /api/v1)
│   │   ├── core/           settings, logging, error envelope
│   │   ├── db/             engine, session, declarative base
│   │   ├── models/         SQLAlchemy models
│   │   ├── schemas/        Pydantic request/response models
│   │   ├── services/       ingestion, normalization, analytics, anomaly_detection,
│   │   │                   investigation, budgeting, notifications, pipeline
│   │   └── workers/        Celery app and scheduled tasks
│   ├── alembic/            database migrations
│   ├── scripts/            sample-data generator
│   └── tests/              pytest suite (runs against PostgreSQL)
├── frontend/               Next.js dashboard and landing page
├── sample-data/            synthetic CSV and a deliberately invalid CSV
├── docs/                   documentation
├── docker-compose.yml
└── .env.example
```

## Known limitations

These are planned for Milestone 8 or later:

- **No authentication yet.** CloudPulse is single-tenant and intended for local use only. Do not expose it to a network.
- Billing ingestion runs synchronously in the upload request. Validating and normalizing 150,000 rows took about 7 seconds in testing, plus database insert time. Very large exports should be split (the upload limit is 20 MB).
- If a corrected export changes a cost that was already imported, the old record stays. Delete the earlier import, then re-import.
- Detection only flags increases. Days already recorded as anomalous are not withdrawn automatically if the underlying data later changes.
- There is no currency conversion. Each currency is analysed separately.
- Real AWS billing integration (CUR or Cost Explorer API), Playwright end-to-end tests and GitHub Actions CI are not implemented yet.

See [docs/anomaly-detection.md](docs/anomaly-detection.md#limitations) for detection-specific limitations.
