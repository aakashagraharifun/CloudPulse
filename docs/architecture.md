# Architecture

CloudPulse is a small modular monolith: one FastAPI application, one Celery worker image and one Next.js frontend, backed by PostgreSQL and Redis. Each concern lives in its own service module, so ingestion, analytics, detection, investigation, budgeting and notifications can evolve independently. There is no microservice or message-bus complexity.

## Components

```
 Browser ──HTTP──► Next.js frontend (:3000)        static/prerendered pages, client-side data fetching
    │
    └──────HTTP (CORS)──► FastAPI API (:8000) ──► PostgreSQL (:5432)   source of truth
                              │      ▲
                              │      └──────────── Celery worker ◄── Redis (:6379) ◄── Celery beat
                              │                        (detection, budgets, retries)     (schedule)
                              └──► SMTP (Mailpit :1025) / webhooks    notifications
```

| Component | Responsibility |
| --- | --- |
| **frontend** (`frontend/`) | Landing page and dashboard. Calls the API directly from the browser (`NEXT_PUBLIC_API_URL`). Holds no business logic. |
| **API** (`backend/app/main.py`) | REST endpoints under `/api/v1`, validation, the consistent error envelope, OpenAPI docs. |
| **worker** (`backend/app/workers/`) | Celery tasks: scheduled anomaly detection (every 6 h), budget evaluation (hourly), retry of failed notifications (every 10 min). |
| **beat** | The Celery scheduler that enqueues those tasks into Redis. |
| **PostgreSQL** | Billing records, imports, detections, incidents, budgets, notification history. |
| **Redis** | Celery broker. |
| **Mailpit** | Local SMTP server with a web inbox, so e-mail alerts can be tested without a real mail server. |

## Backend layering

```
api/v1/*.py        HTTP: parse and validate input (Pydantic), call a service, shape the response
   │
services/*         Business logic, independent of HTTP:
   │                 ingestion/       upload workflow, duplicate protection, sample data
   │                 normalization/   canonical schema, CSV parsing/validation, allocation rules
   │                 analytics/       summaries, series, breakdowns, forecast
   │                 anomaly_detection/ engine.py (pure statistics) + service.py (runs, incidents)
   │                 investigation/   evidence and explanations, incident workflow
   │                 budgeting/       utilization, projection, threshold alerts
   │                 notifications/   e-mail and webhook delivery with logging
   │                 pipeline.py      "after data changes" orchestration
   │
models/*           SQLAlchemy tables (never returned directly; schemas/* define responses)
```

The detection engine (`anomaly_detection/engine.py`) is a pure function with no database access, which makes the statistics easy to unit-test.

## Data flow

### 1. Import

1. `POST /api/v1/imports` receives a multipart CSV. The filename is sanitized and the file type and size are checked. The file is only read into memory and never written to disk.
2. If the SHA-256 matches a completed import, the request returns **409** and nothing is written.
3. A `billing_imports` row is committed with status `processing`.
4. `normalization/normalizer.py` decodes UTF-8 and parses the CSV with exact line numbers. It maps headers through the alias table, then validates and normalizes every row: dates go to UTC calendar days, money becomes exact decimals, and currency and provider codes are checked.
5. If any row is invalid, the import is marked `failed` with up to 200 line/column errors and **no records are stored**.
6. Otherwise each record gets a content fingerprint. Records are inserted in chunks with `ON CONFLICT (fingerprint) DO NOTHING`, so already-stored records are counted as duplicates. Allocation rules fill missing project/environment tags. The import becomes `completed`, all in one transaction.
7. `pipeline.run_post_import_evaluation` runs anomaly detection and budget evaluation, then sends notifications. Failures here are logged and never undo the import.

### 2. Analytics

Every analytics query is scoped to one currency and aggregates in SQL (`SUM` over `NUMERIC`). "As of" is the latest day with data for that currency, so historical or sample data behaves like live data. Days with no records at all are *missing* (`null`). Days that have data but nothing matching a filter are a real zero.

### 3. Detection to incident to notification

A detection run serializes on a PostgreSQL advisory lock. For each currency and configured scope it evaluates the most recent N days. Each anomalous day is stored once (it is unique per scope and day) together with its evidence. The day is then attached to an adjacent unresolved incident, or opens a new one. New incidents trigger notifications to every channel whose minimum severity they meet. The [anomaly detection document](anomaly-detection.md) has the details.

### 4. Budgets

On each evaluation (after imports, hourly via Celery, or through **Check budgets now**), each enabled budget's utilization is computed for the period containing "as of". New threshold crossings are inserted into `budget_alerts`. That table has a unique key on (budget, period, threshold), which is what prevents repeat alerts. One notification is then sent naming the highest new threshold.

## Key design decisions

| Decision | Why |
| --- | --- |
| `NUMERIC` money, decimal strings in JSON | Binary floating point cannot represent money exactly; strings avoid JSON float rounding. |
| All-or-nothing CSV validation | No invalid record is ever silently discarded, and users fix the file once. |
| Content fingerprints with an occurrence index | Identical line items within a file are kept, while overlapping exports are never double-counted. |
| Synchronous ingestion, asynchronous schedules | Users get immediate, detailed validation feedback. Periodic work runs in Celery. |
| Median baselines, robust z-scores, minimum history | Explainable and robust to earlier spikes, and they refuse to judge without enough data (see the detection doc). |
| Deterministic explanations, no LLM | Reproducible, private and testable, and they cannot invent causes. |
| Advisory lock plus unique constraints | Concurrent detection runs cannot create duplicate incidents. |
| Browser calls the API directly (CORS) | A simple local setup that works the same in Docker and in development. |
| Ports bound to `127.0.0.1` | Nothing is exposed to the local network. There is no authentication yet. |

## Error handling and logging

- Every error response uses one envelope: `{"error": {"code", "message", "details"}}`. This covers validation errors (422), domain errors (400/404/409/413/415) and unexpected errors (500, logged with a stack trace and no internal details in the response).
- Logs go to stdout. Set `LOG_JSON=true` for one-JSON-object-per-line structured logs that carry context such as `import_id` and `run_id`.

## Security posture (MVP)

- Local-only by design: all ports are bound to `127.0.0.1` and there is no authentication. Authentication and authorization are scheduled for Milestone 8.
- Secrets live in `.env`, which is git-ignored. `.env.example` holds placeholders only.
- Uploads: `.csv` only, size-limited before and after reading, never written to disk, and the filename is used only as a display label.
- Webhook URLs are masked in API responses because they often embed tokens.
- Containers run as non-root users.
