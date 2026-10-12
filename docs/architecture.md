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
| **API** (`backend/app/main.py`) | REST endpoints under `/api/v1`, authentication and roles, validation, the consistent error envelope, request IDs and the audit log, OpenAPI docs. |
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
| Ports bound to `127.0.0.1` | Nothing is exposed to the local network. Authentication protects the data, but there is no TLS. |
| Opaque, hashed, revocable session tokens | Sign-out and password changes take effect immediately. JWTs could not be revoked without a deny-list. |

## Authentication and authorization

**Model: one workspace, three roles.** Every signed-in user sees the same billing data. The role decides what they may change:

| Role | Can |
| --- | --- |
| viewer | Read everything: analytics, incidents and investigations, budgets, imports, settings values, delivery history |
| member | Everything a viewer can, plus: upload or load billing data, run detection, acknowledge, note, resolve or reopen incidents, create, edit or delete budgets, check budgets |
| admin | Everything a member can, plus: delete imports, change detection settings, manage notification channels (including test sends), allocation rules and users, read the audit log |

*Why not separate organizations?* For a local, single-team tool, multi-tenancy would add an `organization_id` to every table and query without protecting anything more. Roles cover the real need: who may change shared data. Multi-tenancy is a documented future extension.

**Sign-in flow.**

1. On an empty database, `GET /auth/status` returns `setup_required: true`. The login page then shows **Create the admin account**. `POST /auth/setup` is serialized with an advisory lock and only works while no user exists.
2. `POST /auth/login` checks the password and issues a session token: 32 random bytes, URL-safe.
3. The browser sends it as `Authorization: Bearer <token>`. The API stores only `SHA-256(token)` in `user_sessions`, together with its expiry (12 h by default), so a database leak exposes no usable tokens.
4. Each request resolves the token to an active, unexpired, non-revoked session of an active user. If that fails the response is `401`, and the dashboard clears the token and redirects to `/login?next=…`. Only `/dashboard…` paths are accepted for `next`, so there is no open redirect.
5. Sign-out revokes the session. Changing a password revokes all of the user's other sessions. An admin password reset or deactivation revokes all of that user's sessions.

**Passwords.** Passwords are hashed with scrypt (n=2¹⁴, r=8, p=1) and a random salt. They must be 10–128 characters, with no leading or trailing spaces and not trivially repetitive. Login failures return the same message whether or not the e-mail exists. For unknown e-mails the server still verifies against a dummy hash, so response timing reveals nothing. After 5 failures the account is locked for 15 minutes (`429`, `Retry-After`).

**Enforcement.** Every router except health, auth and the data-free CSV template is mounted with a `get_current_user` dependency. Endpoints that change data also declare `require_member` or `require_admin`. `tests/test_auth.py` holds an explicit access policy and calls **every route in the OpenAPI spec** as anonymous, viewer, member and admin. A new endpoint that forgets its guard fails the test suite.

**Recovery.** `python -m scripts.manage_users create-admin | reset-password` works directly against the database. It reads the password from a prompt or `CLOUDPULSE_PASSWORD`, never from the command line, and the action is audited.

**Token storage trade-off.** The dashboard keeps the token in `localStorage`, so it survives a reload. Scripts on the same origin could read it. The mitigations are that the app never renders HTML from data (React escapes everything), tokens expire and can be revoked, and everything is local-only. An HttpOnly cookie behind a same-origin reverse proxy would be the next hardening step for a networked deployment.

## Audit log

`audit_events` records who did what and when, with the client IP and the request ID:

- **Sign-in:** `auth.setup`, `auth.login`, `auth.login_failed` (with the attempted e-mail), `auth.logout`, `auth.password_changed`
- **Users:** `user.created`, `user.updated`, `user.password_reset`
- **Imports and detection:** `import.uploaded`, `import.sample_loaded`, `import.deleted`, `detection.run`, `detection.settings_updated`
- **Configuration:** `budget.*`, `channel.*`, `allocation_rule.*`

Incident actions are recorded in each incident's own timeline (`incident_events`). Admins read the audit log under **Settings → Audit log** or at `GET /api/v1/audit-events`.

## Error handling, logging and request IDs

- Every error response uses one envelope: `{"error": {"code", "message", "details"}}`. This covers validation errors (422), authentication (401) and permission errors (403), domain errors (400/404/409/413/415/429), and unexpected errors.
- **Request IDs.** Each request gets an ID: either a safe incoming `X-Request-ID` (64 characters max, `[A-Za-z0-9._-]`) or a new UUID. It is returned in the `X-Request-ID` response header, attached to every log line (`[request_id]` in text logs, a `request_id` field in JSON logs), and stored on audit events.
- **Unexpected errors (500)** are logged with the full stack trace. The response contains only `internal_error` and the request ID (`details.request_id`), so a user can quote it and an operator can find the trace. No internal details leak.
- **Access log.** One line per request with method, path, status, duration and user ID. Set `LOG_JSON=true` for one-JSON-object-per-line output.

## Security summary

- Authentication and role-based authorization on every non-public endpoint, enforced by tests.
- Passwords hashed with scrypt, token hashes stored instead of tokens, sessions revocable, accounts locked after repeated failures.
- Secrets live in `.env`, which is git-ignored. `.env.example` holds placeholders. CI fails if any `.env` file is ever committed.
- Uploads: `.csv` only, size-limited before and after reading, never written to disk, and the filename is used only as a display label.
- Webhook URLs are masked in API responses because they often embed tokens.
- Ports are bound to `127.0.0.1`. Containers run as non-root users.
- Not yet: TLS, HttpOnly cookie sessions, rate limiting beyond login lockout, multi-tenancy (see the README's known limitations).
