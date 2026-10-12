# CloudPulse frontend

Next.js (App Router, TypeScript strict), Tailwind CSS and Recharts.

```powershell
npm install
npm run dev          # http://localhost:3000 (expects the API on http://127.0.0.1:8000)
npm run lint
npm run typecheck
npm run build
```

Set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` if the API runs elsewhere.
See the repository [README](../README.md), [docs/development.md](../docs/development.md) and [docs/design.md](../docs/design.md).
