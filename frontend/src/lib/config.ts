/**
 * Base URL of the CloudPulse API. The browser calls the API directly, so this
 * must be reachable from the user's machine (FastAPI enables CORS for the
 * Next.js origin). Override with NEXT_PUBLIC_API_URL in frontend/.env.local.
 */
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");
