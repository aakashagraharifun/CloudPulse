# Development guide (Windows, PowerShell, Docker Desktop)

## Prerequisites

| Tool | Version used | Check |
| --- | --- | --- |
| Docker Desktop | 29.x (Compose v2+) | `docker compose version` |
| Python | 3.13 (3.12+ works) | `py --version` |
| Node.js | 22 LTS | `node --version` |
| Git | any recent | `git --version` |

## 1. Configure environment variables

```powershell
cd C:\path\to\CloudPulse
Copy-Item .env.example .env
notepad .env        # set POSTGRES_PASSWORD to any local password
```

`.env` is git-ignored. Never commit it. The backend reads the same file, so the password only lives in one place. Every other setting has a sensible default (see `.env.example`).

## 2. Two ways to run

### A. Everything in Docker (closest to "production")

```powershell
docker compose --profile app up -d --build   # build images and start all services
docker compose --profile app ps              # status; api should be "healthy"
docker compose logs -f api                   # follow API logs (Ctrl+C to stop following)
docker compose --profile app down            # stop and remove containers (data is kept)
```

| Service | URL / port | Notes |
| --- | --- | --- |
| frontend | http://localhost:3000 | Next.js production build |
| api | http://127.0.0.1:8000/docs | Runs `alembic upgrade head` on start |
| worker, beat | — | Celery: scheduled detection, budget checks, notification retries |
| postgres | 127.0.0.1:5432 | Volume `postgres_data` |
| redis | 127.0.0.1:6379 | Volume `redis_data` |
| mailpit | http://127.0.0.1:8025 | Inbox for e-mail alerts (SMTP on 1025) |

**What `--profile app` does:** the API, worker, beat and frontend services belong to the `app` profile, so a plain `docker compose up -d` starts only the infrastructure (Postgres, Redis, Mailpit). That is what you want for option B.

After code changes, rebuild with `docker compose --profile app up -d --build`.

### B. Infrastructure in Docker, code on your machine (hot reload)

```powershell
# Terminal 1 - infrastructure
docker compose up -d                          # postgres, redis, mailpit

# Terminal 2 - backend
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1                   # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements-dev.txt
alembic upgrade head                           # create/upgrade tables
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 3 - frontend
cd frontend
npm install
npm run dev                                    # http://localhost:3000

# Optional terminal 4 - background jobs (Windows needs --pool=solo)
cd backend; .\.venv\Scripts\Activate.ps1
celery -A app.workers.celery_app worker --loglevel=INFO --pool=solo
# and, in another terminal, the scheduler:
celery -A app.workers.celery_app beat --loglevel=INFO
```

The worker is optional for local use: imports already run detection and budget checks immediately. The worker adds the schedules and notification retries.

## 3. Tests and checks

```powershell
# Backend (from backend/, venv active)
pytest                      # 114 tests; uses database "cloudpulse_test" (auto-created)
ruff check .                # lint
ruff format --check .       # formatting (run "ruff format ." to fix)

# Frontend (from frontend/)
npm run lint
npm run typecheck           # regenerates Next.js route types, then runs tsc
npm run build
```

**How the backend tests work:** `tests/conftest.py` creates a separate `cloudpulse_test` database on the same Postgres server and builds the schema by running the real Alembic migrations, which also tests the migrations. It truncates all tables before each test. Your development data in `cloudpulse` is never touched. Docker's Postgres must be running.

Test coverage by area:

| File | Covers |
| --- | --- |
| `test_normalization.py` | Encoding, headers and aliases, AWS CUR, row validation, timezone boundaries, decimals, fingerprints |
| `test_imports_api.py` | Upload workflow, 409 duplicates, overlapping files, 422 validation, size/type limits, filename sanitizing, sample data, allocation rules |
| `test_analytics.py` | Summaries, missing days versus zero, weekly/monthly buckets, breakdowns, currencies, forecast |
| `test_detection_engine.py` | Thresholds, z gate, minimum history, new spend, credits, day-of-week baselines, severity |
| `test_incidents.py` | Exact incidents from the sample data, de-duplication, resolved incidents, workflow API, investigation |
| `test_budgets_notifications.py` | Periods, utilization, alert-once policy, re-notify policy, failed or unreachable channels (real local HTTP server) |

## 4. Database migrations

```powershell
cd backend; .\.venv\Scripts\Activate.ps1
alembic upgrade head                                   # apply
alembic revision --autogenerate -m "describe change"   # after editing app/models/*
alembic check                                          # confirms models and DB match
alembic downgrade -1                                   # undo the last migration
```

Always read an autogenerated migration before applying it. Postgres limits identifier names to 63 characters, so give long constraints an explicit `name=`.

## 5. Sample data

- In the UI: **Imports → Load sample data** generates 90 days ending yesterday and marks the import as sample data.
- From the command line:
  ```powershell
  cd backend; .\.venv\Scripts\Activate.ps1
  python -m scripts.generate_sample_data                         # writes sample-data/synthetic_billing_90d.csv
  python -m scripts.generate_sample_data --end-date 2026-10-11 --days 120 --out my.csv
  ```
- `sample-data/invalid_billing_example.csv` demonstrates validation errors.

To start over, delete the imports on the Imports page. Their billing records are deleted with them.

## 6. Troubleshooting

| Problem | Fix |
| --- | --- |
| `POSTGRES_PASSWORD … must be set` when running compose | Create `.env` from `.env.example` (step 1) |
| API or pytest hangs connecting to the database | Use `127.0.0.1`, not `localhost`. On Windows `localhost` may resolve to IPv6 `::1` first while Docker publishes on IPv4. This is already the default; check you haven't overridden `POSTGRES_HOST` |
| `password authentication failed` | The Postgres volume was created with an older password. Put the original password back in `.env`. Resetting the volume (`docker compose down -v`) **deletes all data**; only do it deliberately |
| Port 5432 / 6379 / 8000 / 3000 already in use | Stop the other program, or change the left-hand port in `docker-compose.yml` |
| Frontend shows "Cannot reach the CloudPulse API" | Start the API, check http://127.0.0.1:8000/api/v1/ready, or set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` |
| Browser console shows CORS errors | Add your frontend origin to `CORS_ORIGINS` in `.env` (a JSON list) and restart the API |
| `uvicorn --reload` stops picking up changes on Windows | Restart uvicorn (a known WatchFiles quirk), or run without `--reload` |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Celery worker exits immediately on Windows | Use `--pool=solo` (prefork is not supported on Windows) |
| An e-mail "sent" but nothing arrives | Locally, e-mail goes to Mailpit: open http://127.0.0.1:8025 |
| `npm audit` reports high-severity issues in `braces` | They come from the dev-only ESLint toolchain (`eslint-config-next`). The suggested `--force` fix downgrades Next to 14, so it is intentionally not applied |
| A Next.js warning mentions a `pnpm-lock.yaml` outside the repository | Harmless. A lock file in your user folder is ignored |

## 7. Conventions

- Python: ruff (lint + format), line length 100, type hints throughout. FastAPI routes stay thin and logic lives in `services/`.
- TypeScript strict mode, the ESLint Next.js config, and Tailwind tokens from `globals.css` (see [design.md](design.md)).
- Money: never use `float` in the backend. Use `Decimal` or `NUMERIC`.
- Every API error goes through `app.core.errors` (`AppError`, `NotFoundError`, `ConflictError`).
- Never commit `.env`, `.venv`, `node_modules` or `.next` (see `.gitignore`).
