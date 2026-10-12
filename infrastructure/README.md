# Infrastructure

CloudPulse is local-first: all infrastructure is defined in files that sit next to the code they run.

| File | Purpose |
| --- | --- |
| [`../docker-compose.yml`](../docker-compose.yml) | PostgreSQL 16, Redis 7 and Mailpit; plus the API, Celery worker, Celery beat and frontend under the `app` profile |
| [`../backend/Dockerfile`](../backend/Dockerfile) | One image for the API, worker and beat (non-root user) |
| [`../frontend/Dockerfile`](../frontend/Dockerfile) | Multi-stage Next.js standalone build (non-root user) |
| [`../.env.example`](../.env.example) | Every configuration variable with placeholder values |

No cloud resources are created by this project. Deployment manifests (for example a managed Postgres or container hosting) are intentionally out of scope for the MVP. See [docs/development.md](../docs/development.md) to run everything locally.
